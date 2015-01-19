import argparse
import concurrent.futures
import time
import pytz
import datetime
import dateutil.parser
import psycopg2.extensions

from pynab import log, log_descriptor
from pynab.db import db_session, Group, Binary, Miss, engine, Segment

import pynab.groups
import pynab.binaries
import pynab.releases
import pynab.tvrage
import pynab.rars
import pynab.nfos
import pynab.imdb
import pynab.debug
import config


def update(group_name):
    try:
        return pynab.groups.scan(group_name, limit=config.scan.get('group_scan_limit', 2000000))
    except Exception as e:
        log.error(e + ": " + 'scan: nntp server is flipping out, hopefully they fix their shit')


def backfill(group_name, date=None):
    if date:
        date = pytz.utc.localize(dateutil.parser.parse(args.date))
    else:
        date = pytz.utc.localize(datetime.datetime.now() - datetime.timedelta(config.scan.get('backfill_days', 10)))
    try:
        return pynab.groups.scan(group_name, direction='backward', date=date, limit=config.scan.get('group_scan_limit', 2000000))
    except Exception as e:
        log.error(e + ": " + 'scan: nntp server is flipping out, hopefully they fix their shit')


def scan_missing(group_name):
    try:
        return pynab.groups.scan_missing_segments(group_name)
    except Exception as e:
        log.error(e + ": " + 'scan: nntp server is flipping out, hopefully they fix their shit')


def process():
    # process binaries
    log.info('scan: processing binaries...')
    pynab.binaries.process()

    # process releases
    log.info('scan: processing releases...')
    pynab.releases.process()


def daemonize(pidfile):
    try:
        import traceback
        from daemonize import Daemonize

        fds = []
        if log_descriptor:
            fds = [log_descriptor]

        daemon = Daemonize(app='pynab', pid=pidfile, action=main, keep_fds=fds)
        daemon.start()
    except SystemExit:
        raise
    except:
        log.critical(traceback.format_exc())


def main(mode='update', group=None, date=None):
    log.info('scan: starting {}...'.format(mode))

    iterations = 0
    while True:
        iterations += 1

        # refresh the db session each iteration, just in case
        with db_session() as db:
            if db.query(Segment).count() > config.scan.get('early_process_threshold', 50000000):
                log.info('scan: backlog of segments detected, processing first')
                process()

            if not group:
                active_groups = [group.name for group in db.query(Group).filter(Group.active==True).all()]
            else:
                if db.query(Group).filter(Group.name==group).first():
                    active_groups = [group]
                else:
                    log.error('scan: no such group exists')
                    return

            if active_groups:
                with concurrent.futures.ThreadPoolExecutor(config.scan.get('update_threads', None)) as executor:
                    # if maxtasksperchild is more than 1, everything breaks
                    # they're long processes usually, so no problem having one task per child
                    if mode == 'backfill':
                        result = [executor.submit(backfill, active_group, date) for active_group in active_groups]
                    else:
                        result = [executor.submit(update, active_group) for active_group in active_groups]

                    for r in concurrent.futures.as_completed(result):
                        data = r.result()

                    # don't retry misses during backfill, it ain't gonna happen
                    if config.scan.get('retry_missed') and not mode == 'backfill':
                        miss_groups = [group_name for group_name, in db.query(Miss.group_name).group_by(Miss.group_name).all()]
                        miss_result = [executor.submit(scan_missing, miss_group) for miss_group in miss_groups]

                        # no timeout for these, because it could take a while
                        for r in concurrent.futures.as_completed(miss_result):
                            data = r.result()

                process()

                # clean up dead binaries and parts
                if config.scan.get('dead_binary_age', 1) != 0:
                    dead_time = pytz.utc.localize(datetime.datetime.now()) - datetime.timedelta(days=config.scan.get('dead_binary_age', 3))

                    dead_binaries = db.query(Binary).filter(Binary.posted<=dead_time).delete()
                    db.commit()

                    log.info('scan: deleted {} dead binaries'.format(dead_binaries))
            else:
                log.info('scan: no groups active, cancelling pynab.py...')
                break

            # vacuum the segments, parts and binaries tables
            log.info('scan: vacuuming relevant tables...')
            conn = engine.connect()
            conn.connection.connection.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)

            # this may look weird, but we want to reset iterations even if full_vacuums are off
            # so it doesn't count to infinity
            if iterations >= config.scan.get('full_vacuum_iterations', 288):
                if config.scan.get('full_vacuum', True):
                    conn.execute('VACUUM FULL ANALYZE binaries')
                    conn.execute('VACUUM FULL ANALYZE parts')
                    conn.execute('VACUUM FULL ANALYZE segments')
                iterations = 0
            else:
                conn.execute('VACUUM ANALYZE binaries')
                conn.execute('VACUUM ANALYZE parts')
                conn.execute('VACUUM ANALYZE segments')

            conn.close()
            db.close()

        # don't bother waiting if we're backfilling, just keep going
        if mode == 'update':
            # wait for the configured amount of time between cycles
            update_wait = config.scan.get('update_wait', 300)
            log.info('scan: sleeping for {:d} seconds...'.format(update_wait))
            time.sleep(update_wait)


if __name__ == '__main__':
    argparser = argparse.ArgumentParser(description="Pynab main scanning script")
    argparser.add_argument('-d', '--daemonize', action='store_true', help='run as a daemon')
    argparser.add_argument('-p', '--pid-file', help='pid file (when -d)')
    argparser.add_argument('-b', '--backfill', action='store_true', help='backfill groups')
    argparser.add_argument('-g', '--group', help='group to scan')
    argparser.add_argument('-D', '--date', help='backfill to date')

    args = argparser.parse_args()

    if args.daemonize:
        pidfile = args.pid_file or config.scan.get('pid_file')
        if not pidfile:
            log.error("A pid file is required to run as a daemon, please supply one either in the config file '{}' or as argument".format(config.__file__))
        else:
            daemonize(pidfile)
    else:
        if args.backfill:
            mode = 'backfill'
        else:
            mode = 'update'
        main(mode=mode, group=args.group, date=args.date)