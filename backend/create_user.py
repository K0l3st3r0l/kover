#!/usr/bin/env python3
"""
Script para crear usuarios en Kover
Uso: python create_user.py
"""

import os
import sys
from getpass import getpass

# Agregar el directorio app al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.user import User

def create_user():
    print("=== Crear Usuario en Kover ===\n")
    
    email = input("Email: ").strip()
    username = input("Username: ").strip()
    password = getpass("Password: ")
    password_confirm = getpass("Confirm Password: ")
    
    if not email or not username or not password:
        print("❌ Error: Todos los campos son requeridos")
        return
    
    if password != password_confirm:
        print("❌ Error: Las contraseñas no coinciden")
        return
    
    if len(password) < 6:
        print("❌ Error: La contraseña debe tener al menos 6 caracteres")
        return
    
    db = SessionLocal()
    
    try:
        # Verificar si el usuario ya existe
        existing = db.query(User).filter(
            (User.email == email) | (User.username == username)
        ).first()
        
        if existing:
            print(f"❌ Error: El email o username ya está registrado")
            return
        
        # Crear usuario
        hashed_password = User.hash_password(password)
        new_user = User(
            email=email,
            username=username,
            hashed_password=hashed_password
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        print(f"\n✅ Usuario creado exitosamente!")
        print(f"   ID: {new_user.id}")
        print(f"   Email: {new_user.email}")
        print(f"   Username: {new_user.username}")
        
    except Exception as e:
        print(f"❌ Error al crear usuario: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_user()
