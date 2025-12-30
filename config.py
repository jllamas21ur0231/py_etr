class Config:
    SECRET_KEY = 'your_strong_secret_key_here'
    MYSQL_HOST = 'localhost'
    MYSQL_USER = 'root'
    MYSQL_PASSWORD = ''  # change if you have a password
    MYSQL_DB = 'py_etr'  # ← Changed from 'ecommerce_db' to 'py_etr'
    MYSQL_CURSORCLASS = 'DictCursor'