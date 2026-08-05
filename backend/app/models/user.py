from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from datetime import datetime
from ..database import Base
import bcrypt

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    # Legacy: el saldo se deriva de las transacciones (ver services/cash_ledger.py).
    # Se mantiene como respaldo para cuentas sin ancla configurada.
    cash_balance = Column(Float, default=0.0, nullable=False)
    # Ancla del saldo derivado: saldo conocido a una fecha. Los flujos posteriores
    # se suman sobre él, porque el historial no trae los depósitos antiguos.
    cash_opening_balance = Column(Float, default=0.0, nullable=False)
    cash_opening_date = Column(DateTime(timezone=True), nullable=True)
    # Distribución actual del usuario en fondos AFP (ej: {"A":0,"B":0,"C":0,"D":40,"E":60})
    afp_allocation = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def verify_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode('utf-8'), self.hashed_password.encode('utf-8'))

    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
