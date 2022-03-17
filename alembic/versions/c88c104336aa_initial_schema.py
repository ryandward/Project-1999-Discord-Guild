"""initial schema

Revision ID: c88c104336aa
Revises:
Create Date: 2022-03-17 09:48:36.898927

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c88c104336aa'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'races',
        sa.Column('race', sa.Text),
        sa.Column('id', sa.Integer, primary_key=True)
    )

    op.create_table(
        'raids',
        sa.Column('raid', sa.Text),
        sa.Column('type', sa.Text),
        sa.Column('modifier', sa.Integer),
        sa.Column('id', sa.Integer, primary_key=True)
    )

    op.create_table(
        'class_definitions',
        sa.Column('class_name', sa.Text),
        sa.Column('character_class', sa.Text),
        sa.Column('id', sa.Integer, primary_key=True)
    )

    op.create_table(
        'bank',
        sa.Column('banker', sa.Text),
        sa.Column('location', sa.Text),
        sa.Column('name', sa.Text),
        sa.Column('eq_item_id', sa.Text),
        sa.Column('count', sa.Integer),
        sa.Column('slots', sa.Integer),
        sa.Column('time', sa.Text),
        sa.Column('id', sa.Integer, primary_key=True)
    )

    op.create_table(
        'trash',
        sa.Column('name', sa.Text),
        sa.Column('id', sa.Integer, primary_key=True)
    )

    op.create_table(
        'items',
        sa.Column('name', sa.Text),
        sa.Column('date', sa.Text),
        sa.Column('item', sa.Text),
        sa.Column('dkp_spent', sa.Integer),
        sa.Column('note', sa.Text),
        sa.Column('discord_id', sa.Text, sa.ForeignKey('dkp.discord_id')),
        sa.Column('id', sa.Integer, primary_key=True)
    )

    op.create_table(
        'census',
        sa.Column('discord_id', sa.Text, sa.ForeignKey('dkp.discord_id')),
        sa.Column('name', sa.Text, unique=True),
        sa.Column('character_class', sa.Text),
        sa.Column('level', sa.Integer),
        sa.Column('status', sa.Text),
        sa.Column('time', sa.Integer),
        sa.Column('id', sa.Integer, primary_key=True)
    )

    op.create_table(
        'dkp',
        sa.Column('discord_name', sa.Text),
        sa.Column('earned_dkp', sa.Integer),
        sa.Column('spent_dkp', sa.Integer),
        sa.Column('discord_id', sa.Text, unique=True),
        sa.Column('date_joined', sa.Text),
        sa.Column('id', sa.Integer, primary_key=True)
    )

    op.create_table(
        'attendance',
        sa.Column('raid', sa.Text, sa.ForeignKey('raids.raid')),
        sa.Column('name', sa.Text),
        sa.Column('date', sa.Text),
        sa.Column('discord_id', sa.Text),
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('modifier', sa.Integer)
    )

def downgrade():
    pass
