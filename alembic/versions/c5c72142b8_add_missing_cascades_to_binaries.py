"""add missing cascades to binaries

Revision ID: c5c72142b8
Revises: 1cbc2db68e8
Create Date: 2015-01-11 09:38:25.203200

"""

# revision identifiers, used by Alembic.
revision = 'c5c72142b8'
down_revision = '1cbc2db68e8'

from alembic import op
import sqlalchemy as sa


def upgrade():
    # add sfv fk since it was missing ?_?

    op.drop_constraint('releases_nzb_id_fkey', 'releases')
    op.drop_constraint('releases_nfo_id_fkey', 'releases')
    #op.drop_constraint('releases_sfv_id_fkey', 'releases')

    op.create_foreign_key('releases_nzb_id_fkey', 'releases', 'nzbs', ['nzb_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('releases_nfo_id_fkey', 'releases', 'nfos', ['nfo_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('releases_sfv_id_fkey', 'releases', 'sfvs', ['sfv_id'], ['id'], ondelete='CASCADE')


def downgrade():
    # no downgrade needed

    ### commands auto generated by Alembic - please adjust! ###
    pass
    ### end Alembic commands ###