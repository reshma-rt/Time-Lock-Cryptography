from cryptography.fernet import Fernet

def encrypt_message(message):
    key = Fernet.generate_key()
    f = Fernet(key)
    encrypted = f.encrypt(message.encode())
    return key, encrypted