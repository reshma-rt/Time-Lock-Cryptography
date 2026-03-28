import requests

def create_sample_files():
    """
    Run this script while the Flask server (`python app.py`) is running locally.
    It will interact with the API to automatically generate two sample `.enc` targets.
    """
    print("Initiating automated encryption processes...")
    try:
        url_text = "http://127.0.0.1:8000/encrypt/text"
        
        # 1. Base Encryption Scenario (No Extra Password)
        payload_1 = {
            "message": "Hello Administrator! This payload validates the hardware threading capabilities and logic loops of the Time-Lock puzzle module entirely via server computation.", 
            "delay": "10"
        }
        res_1 = requests.post(url_text, json=payload_1)
        if res_1.status_code == 200:
            name_1 = res_1.json()['filename']
            b64_cipher_1 = res_1.json()['ciphertext_b64']
            
            import base64
            with open(name_1, 'wb') as f:
                f.write(base64.b64decode(b64_cipher_1))
            print(f"[*] Successfully generated basic puzzle: {name_1}")
            
        # 2. Dual-Layer Encryption (With AES PBKDF2 Password wrapping)
        payload_2 = {
            "message": "Top Secret Password Message! SHA256 integrity confirms tampered blocks fail silently until validated.", 
            "delay": "25", 
            "password": "supersecret"
        }
        res_2 = requests.post(url_text, json=payload_2)
        if res_2.status_code == 200:
            name_2 = res_2.json()['filename']
            b64_cipher_2 = res_2.json()['ciphertext_b64']
            
            with open(name_2, 'wb') as f:
                f.write(base64.b64decode(b64_cipher_2))
            print(f"[*] Successfully generated PBKDF2 Password protected puzzle: {name_2} (Pass: supersecret)")
            
    except requests.exceptions.ConnectionError:
         print("ERROR: Connection failed. Ensure the flask server (app.py) is booted at 127.0.0.1:8000")

if __name__ == "__main__":
    create_sample_files()
