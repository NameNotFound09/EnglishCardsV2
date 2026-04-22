import sqlalchemy
from .db_session import SqlAlchemyBase

class Bank(SqlAlchemyBase):
    __tablename__ = 'banks'
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    user_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True)
    alice_id = sqlalchemy.Column(sqlalchemy.String, nullable=True, unique=True)
    bank = sqlalchemy.Column(sqlalchemy.JSON, nullable=True)