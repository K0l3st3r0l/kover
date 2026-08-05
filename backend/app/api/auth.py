from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from ..database import get_db
from ..models.user import User
from ..services.cash_ledger import compute_cash_balance
from ..utils.auth import create_access_token, get_current_user

router = APIRouter()

# DISABLED: Public registration is disabled for security
# Only create users via CLI script
# @router.post("/register", response_model=Token)
# def register(user_data: UserRegister, db: Session = Depends(get_db)):
#     ...

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict

@router.post("/login", response_model=Token)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    # Find user
    user = db.query(User).filter(User.email == user_data.email).first()
    
    if not user or not user.verify_password(user_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    # Create access token
    access_token = create_access_token(data={"user_id": user.id})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username
        }
    }

class CashBalanceUpdate(BaseModel):
    """Fija el ancla del saldo derivado: cuánto había y desde cuándo contar."""
    cash_balance: float                      # saldo conocido a `opening_date`
    opening_date: Optional[datetime] = None  # sin fecha, cuenta todo el historial


@router.get("/cash")
def get_cash_balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Saldo de caja derivado de las transacciones, con su desglose.

    `cash_balance` sigue en la respuesta con el mismo nombre para no romper a los
    consumidores; lo que cambió es que ya no es un número escrito a mano.
    """
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return compute_cash_balance(db, user)


@router.put("/cash")
def update_cash_balance(
    data: CashBalanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fija el saldo inicial desde el que se derivan los flujos.

    El valor que se manda es el saldo **a esa fecha**, no el saldo actual: los
    movimientos posteriores se suman encima. Para IB, el "Starting Cash" del
    Cash Report en la fecha de inicio del extracto.
    """
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    user.cash_opening_balance = data.cash_balance
    user.cash_opening_date = data.opening_date
    db.commit()
    db.refresh(user)
    return compute_cash_balance(db, user)

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username
    }

class AfpAllocationUpdate(BaseModel):
    allocation: dict

@router.get("/afp-allocation")
def get_afp_allocation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retorna la distribución actual en fondos AFP del usuario"""
    user = db.query(User).filter(User.id == current_user.id).first()
    return {"allocation": user.afp_allocation}

@router.put("/afp-allocation")
def update_afp_allocation(
    data: AfpAllocationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Actualiza la distribución actual en fondos AFP del usuario"""
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.afp_allocation = data.allocation
    db.commit()
    db.refresh(user)
    return {"allocation": user.afp_allocation}

class ChangePassword(BaseModel):
    current_password: str
    new_password: str

@router.post("/change-password")
def change_password(
    data: ChangePassword,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.verify_password(data.current_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect"
        )
    if len(data.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be at least 6 characters"
        )
    current_user.hashed_password = User.hash_password(data.new_password)
    db.commit()
    return {"message": "Password changed successfully"}
