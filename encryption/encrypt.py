from cryptography.fernet import Fernet

def encrypt_message(message):
    key = Fernet.generate_key()
    cipher = Fernet(key)
    encrypted = cipher.encrypt(message.encode())
    return key, encrypted