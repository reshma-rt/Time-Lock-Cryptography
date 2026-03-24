from cryptography.fernet import Fernet

def decrypt_message(encrypted, key):
    cipher = Fernet(key)
    return cipher.decrypt(encrypted).decode()