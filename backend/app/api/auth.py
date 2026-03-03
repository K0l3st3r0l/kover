from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from ..database import get_db
from ..models.user import User
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
    cash_balance: float

@router.get("/cash")
def get_cash_balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retorna el saldo de cash disponible del usuario"""
    user = db.query(User).filter(User.id == current_user.id).first()
    return {"cash_balance": user.cash_balance or 0.0}

@router.put("/cash")
def update_cash_balance(
    data: CashBalanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Actualiza el saldo de cash disponible del usuario"""
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user.cash_balance = data.cash_balance
    db.commit()
    db.refresh(user)
    return {"cash_balance": user.cash_balance}

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username
    }

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
