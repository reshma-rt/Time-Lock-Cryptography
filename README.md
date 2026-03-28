# Chronos - Advanced Time-Lock Cryptography System

Chronos is a robust, production-grade hybrid cryptographic web application utilizing Flask. It enables users to strictly seal files and text messages using mathematically constrained Time-Lock Puzzles, rendering decryption completely impossible until a user-defined computational threshold (time delay) is reached.

## 🌟 Core Features

- **Hybrid Encryption**: Combines AES-256 (EAX Mode) for ultra-fast, authenticated payload encryption, while locking the AES blueprint inside a Rivest-Shamir-Wagner (RSW) Time-Lock mathematical puzzle structure (`a^(2^t) mod n`).
- **Dual-Layered Security**: Optional secondary password locking (PBKDF2 - 25,000 internal iterations) prevents forced puzzle decryption without the original password parameters.
- **Asynchronous & Threaded Engine**: Decryption math structures are assigned to isolated, dedicated Daemon background hardware threads, keeping the underlying Node interface and HTTP routing extremely responsive. 
- **Real-Time Tracking & Graphs**: Includes high-frequency 500ms status polling to provide live iteration logs, percentage bars, and a dedicated Chart.js UI mapping dynamic hardware computation completion times vs delay targets.
- **SHA256 Integrity Architecture**: Prevents bit rot or malicious modification to the `.enc` array format, checking native payload integrity upon puzzle unlock.

## 🚀 Installation & Setup

1. **Prerequisites**: Ensure you have Python 3.8+ installed. 
2. **Dependencies**: From within the master directory, install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the Interface**:
   ```bash
   python app.py
   ```
4. **Access UI**: Open your web browser and navigate to `http://127.0.0.1:8000/`

## 🧪 Testing the Cryptography (Test Cases)

We have provided a dedicated automated test suite that directly negotiates with the backend REST endpoints to verify time-lock validity and generate sample `.enc` shells for you.

To generate sample encrypted payloads, run the script from a secondary terminal while `app.py` is running:

```bash
python test_cases.py
```

This will automatically create two sample files in your working directory:
1. `[UUID-1].enc`: A mathematically locked basic text package (no password).
2. `[UUID-2].enc`: A PBKDF2 Password-protected package. (The password is `supersecret`).

**How to test decryption**:
1. Open the UI (`localhost:8000`).
2. Go to the **Decrypt** tab.
3. Upload the newly generated `.enc` files.
4. Input the password `supersecret` if testing the second file.
5. Click **Initiate Time-Lock Reversal** and watch the live background decryption thread map your hardware's CPU speed dynamically!

## 📁 Architecture Overview

- `/app.py` - Flask web server, dynamic API routing, and daemon threading structures.
- `/crypto.py` - Core cryptography library: Prime derivations, Modular Squaring, AES execution, and PBKDF2 security hooks.
- `/data/db.py` - SQLite instantiation and threaded logging for tracking CPU processing arrays.
- `/static` & `/templates` - Modern Glassmorphism CSS styling, Chart.js metrics, and async Javascript polling. 

## 🛡️ Educational Constraints Notice
For genuine operational deployment, the `SQUARINGS_PER_SECOND` integer inside `crypto.py` must be specifically calibrated towards your underlying CPU server capabilities to accurately map 'Seconds' into 'Squarings'. The default variable assumes ~10,000 squarings per second format.
