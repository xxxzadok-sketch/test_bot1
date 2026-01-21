import sqlite3
import logging
from config import DB_NAME
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        self.create_tables()
        self.fix_menu_categories()
        self.add_payment_method_column()  # <-- Добавьте эту строку

    def get_moscow_time(self):
        """Получить текущее время в московском часовом поясе"""
        tz = pytz.timezone('Europe/Moscow')
        return datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')

    def create_tables(self):
        """Создание всех таблиц с правильной структурой"""
        cursor = self.conn.cursor()

        # Сначала создаем все остальные таблицы
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                bonus_balance INTEGER DEFAULT 0,
                registration_date TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                referred_by INTEGER DEFAULT NULL,
                FOREIGN KEY (referred_by) REFERENCES users (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                type TEXT, -- 'earn' или 'spend'
                description TEXT,
                date TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                booking_date TEXT,
                booking_time TEXT,
                guests INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bonus_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER UNIQUE,
                bonus_awarded BOOLEAN DEFAULT FALSE,
                created_at TEXT,
                FOREIGN KEY (referrer_id) REFERENCES users (id),
                FOREIGN KEY (referred_id) REFERENCES users (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_number INTEGER,
                admin_id INTEGER,
                status TEXT DEFAULT 'active', -- 'active' или 'closed'
                created_at TEXT,
                closed_at TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                item_name TEXT,
                price INTEGER,
                quantity INTEGER DEFAULT 1,
                added_at TEXT,
                FOREIGN KEY (order_id) REFERENCES orders (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS menu_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                price INTEGER,
                category TEXT,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')

        # Проверяем, существует ли уже таблица shifts с правильным индексом
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shifts'")
        shifts_table_exists = cursor.fetchone()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_shift_month'")
        index_exists = cursor.fetchone()

        if not shifts_table_exists or not index_exists:
            # Нужно создать или обновить таблицу shifts
            print("🔄 Создаем/обновляем таблицу shifts...")

            # Временно отключаем foreign keys
            cursor.execute('PRAGMA foreign_keys = OFF')

            # Переименовываем существующие таблицы если они есть
            if shifts_table_exists:
                print("🔄 Переименовываем старую таблицу shifts...")
                cursor.execute('ALTER TABLE shifts RENAME TO shifts_old')

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shift_sales'")
            shift_sales_exists = cursor.fetchone()

            if shift_sales_exists:
                print("🔄 Переименовываем старую таблицу shift_sales...")
                cursor.execute('ALTER TABLE shift_sales RENAME TO shift_sales_old')

            # Создаем новую таблицу смен с составным уникальным ключом
            cursor.execute('''
                CREATE TABLE shifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shift_number INTEGER,
                    month_year TEXT, -- Формат: 'YYYY-MM' для группировки по месяцам
                    admin_id INTEGER,
                    opened_at TEXT,
                    closed_at TEXT,
                    total_revenue INTEGER DEFAULT 0,
                    total_orders INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'open',
                    FOREIGN KEY (admin_id) REFERENCES users (id)
                )
            ''')

            # Создаем составной уникальный индекс если его нет
            if not index_exists:
                cursor.execute('CREATE UNIQUE INDEX idx_shift_month ON shifts (shift_number, month_year)')
                print("✅ Составной уникальный индекс создан")
            else:
                print("✅ Индекс уже существует")

            # Создаем таблицу статистики продаж
            cursor.execute('''
                CREATE TABLE shift_sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shift_id INTEGER,
                    item_name TEXT,
                    quantity INTEGER,
                    total_amount INTEGER,
                    FOREIGN KEY (shift_id) REFERENCES shifts (id)
                )
            ''')

            # Восстанавливаем данные из старой таблицы если она существовала
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shifts_old'")
            if cursor.fetchone():
                print("🔄 Восстанавливаем данные из старой таблицы shifts...")
                cursor.execute('''
                    INSERT INTO shifts (id, shift_number, month_year, admin_id, opened_at, closed_at, 
                                      total_revenue, total_orders, status)
                    SELECT id, shift_number, 
                           CASE 
                               WHEN month_year IS NOT NULL THEN month_year
                               ELSE substr(opened_at, 1, 7)
                           END as month_year,
                           admin_id, opened_at, closed_at, total_revenue, total_orders, status
                    FROM shifts_old
                    ORDER BY id
                ''')

                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shift_sales_old'")
                if cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO shift_sales (shift_id, item_name, quantity, total_amount)
                        SELECT shift_id, item_name, quantity, total_amount
                        FROM shift_sales_old
                    ''')

                # Удаляем временные таблицы
                cursor.execute('DROP TABLE IF EXISTS shifts_old')
                cursor.execute('DROP TABLE IF EXISTS shift_sales_old')

                print("✅ Данные успешно восстановлены")

            # Включаем foreign keys обратно
            cursor.execute('PRAGMA foreign_keys = ON')
        else:
            print("✅ Таблица shifts уже существует с правильным индексом")

        self.conn.commit()

        # Проверяем и добавляем отсутствующие колонки
        self._update_schema()

        # После создания таблицы заполнить её данными
        self.populate_menu_items()

        # Проверяем и исправляем категории меню
        self.fix_menu_categories()

    def _update_schema(self):
        """Обновляет схему базы данных, добавляя отсутствующие колонки"""
        cursor = self.conn.cursor()

        # Проверяем наличие колонки referred_by в таблице users
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'referred_by' not in columns:
            print("🔄 Добавляем колонку referred_by в таблицу users...")
            cursor.execute('ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT NULL')
            self.conn.commit()
            print("✅ Колонка referred_by добавлена")

        # Проверяем наличие колонки closed_at в таблице orders
        cursor.execute("PRAGMA table_info(orders)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'closed_at' not in columns:
            print("🔄 Добавляем колонку closed_at в таблицу orders...")
            cursor.execute('ALTER TABLE orders ADD COLUMN closed_at TEXT')
            self.conn.commit()
            print("✅ Колонка closed_at добавлена")

        # ========== ДОБАВЛЕНО: Проверка payment_method в orders ==========
        # Нужно заново получить колонки, так как orders мог измениться
        cursor.execute("PRAGMA table_info(orders)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'payment_method' not in columns:
            print("🔄 Добавляем колонку payment_method в таблицу orders...")
            cursor.execute('ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT NULL')
            self.conn.commit()
            print("✅ Колонка payment_method добавлена")
        # ========== КОНЕЦ ДОБАВЛЕНИЯ ==========

        # Проверяем наличие колонку month_year в таблице shifts
        cursor.execute("PRAGMA table_info(shifts)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'month_year' not in columns:
            print("🔄 Добавляем колонку month_year в таблицу shifts...")
            cursor.execute('ALTER TABLE shifts ADD COLUMN month_year TEXT')

            # Обновляем существующие записи
            cursor.execute('SELECT id, opened_at FROM shifts')
            shifts = cursor.fetchall()
            for shift_id, opened_at in shifts:
                if opened_at:
                    month_year = opened_at[:7]  # Берем YYYY-MM
                    cursor.execute('UPDATE shifts SET month_year = ? WHERE id = ?', (month_year, shift_id))

            self.conn.commit()
            print("✅ Колонка month_year добавлена")

        # Проверяем наличие колонки is_active в таблице menu_items
        cursor.execute("PRAGMA table_info(menu_items)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'is_active' not in columns:
            print("🔄 Добавляем колонку is_active в таблицу menu_items...")
            cursor.execute('ALTER TABLE menu_items ADD COLUMN is_active BOOLEAN DEFAULT TRUE')
            self.conn.commit()
            print("✅ Колонка is_active добавлена")

    def fix_menu_categories(self):
        """Исправить категории в меню если необходимо"""
        cursor = self.conn.cursor()

        # Список кальянов для проверки
        hookah_items = ["Пенсионный", "Стандарт", "Премиум", "Фруктовая чаша", "Сигарный", "Парфюм"]

        for item_name in hookah_items:
            cursor.execute('SELECT category FROM menu_items WHERE name = ?', (item_name,))
            result = cursor.fetchone()

            if result and result[0] != 'Кальяны':
                print(f"🔄 Исправляем категорию для {item_name}: было '{result[0]}', станет 'Кальяны'")
                cursor.execute('UPDATE menu_items SET category = ? WHERE name = ?', ('Кальяны', item_name))
            elif not result:
                print(f"⚠️ Позиция {item_name} не найдена в базе данных")

        self.conn.commit()
        print("✅ Категории меню проверены и исправлены при необходимости")

    def populate_menu_items(self):
        """Заполнить таблицу menu_items базовыми данными"""
        cursor = self.conn.cursor()

        # Проверяем, есть ли уже данные в таблице
        cursor.execute('SELECT COUNT(*) FROM menu_items')
        count = cursor.fetchone()[0]

        if count == 0:
            menu_items = [
                # Кальяны
                ("Пенсионный", 800, "Кальяны"),
                ("Стандарт", 1000, "Кальяны"),
                ("Премиум", 1200, "Кальяны"),
                ("Фруктовая чаша", 1500, "Кальяны"),
                ("Сигарный", 1500, "Кальяны"),
                ("Парфюм", 2000, "Кальяны"),

                # Напитки
                ("Вода", 100, "Напитки"),
                ("Кола 0,5л", 100, "Напитки"),
                ("Кола/Фанта/Спрайт 1л", 200, "Напитки"),
                ("Пиво/Энергетик", 200, "Напитки"),

                # Коктейли
                ("В/кола", 400, "Коктейли"),
                ("Санрайз", 400, "Коктейли"),
                ("Лагуна", 400, "Коктейли"),
                ("Фиеро", 400, "Коктейли"),
                ("Пробирки", 600, "Коктейли"),

                # Чай
                ("Да Хун Пао", 400, "Чай"),
                ("Те Гуань Инь", 400, "Чай"),
                ("Шу пуэр", 400, "Чай"),
                ("Сяо Чжун", 400, "Чай"),
                ("Юэ Гуан Бай", 400, "Чай"),
                ("Габа", 400, "Чай"),
                ("Гречишный", 400, "Чай"),
                ("Медовая дыня", 400, "Чай"),
                ("Малина/Мята", 400, "Чай"),
                ("Наглый фрукт", 400, "Чай"),
                ("Вишневый пуэр", 500, "Чай"),
                ("Марроканский", 500, "Чай"),
                ("Голубика", 500, "Чай"),
                ("Смородиновый", 500, "Чай"),
                ("Клубничный", 500, "Чай"),
                ("Облепиховый", 500, "Чай")
            ]

            for name, price, category in menu_items:
                try:
                    cursor.execute(
                        'INSERT INTO menu_items (name, price, category, is_active) VALUES (?, ?, ?, ?)',
                        (name, price, category, True)
                    )
                except sqlite3.IntegrityError:
                    # Если позиция уже существует, пропускаем
                    continue

            self.conn.commit()
            print("✅ Таблица menu_items заполнена данными")

    # НОВЫЕ МЕТОДЫ ДЛЯ УПРАВЛЕНИЯ МЕНЮ
    def get_all_menu_categories(self):
        """Получить все категории меню"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT category FROM menu_items WHERE is_active = TRUE ORDER BY category')
        categories = cursor.fetchall()
        return [category[0] for category in categories] if categories else []

    def get_menu_items_by_category(self, category):
        """Получить все позиции меню по категории"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT id, name, price, category, is_active 
            FROM menu_items 
            WHERE category = ? AND is_active = TRUE 
            ORDER BY name
        ''', (category,))
        return cursor.fetchall()

    def get_all_menu_items(self):
        """Получить все позиции меню"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT id, name, price, category, is_active 
            FROM menu_items 
            ORDER BY category, name
        ''')
        return cursor.fetchall()

    def get_menu_item_by_id(self, item_id):
        """Получить позицию меню по ID"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, name, price, category, is_active FROM menu_items WHERE id = ?', (item_id,))
        return cursor.fetchone()

    def get_menu_item_by_name(self, name):
        """Получить позицию меню по названию"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, name, price, category, is_active FROM menu_items WHERE name = ?', (name,))
        return cursor.fetchone()

    def add_menu_item(self, name, price, category):
        """Добавить новую позицию в меню"""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO menu_items (name, price, category, is_active) VALUES (?, ?, ?, ?)',
                (name, price, category, True)
            )
            self.conn.commit()
            return True, "✅ Позиция успешно добавлена"
        except sqlite3.IntegrityError:
            return False, "❌ Позиция с таким названием уже существует"
        except Exception as e:
            return False, f"❌ Ошибка при добавлении: {str(e)}"

    def update_menu_item(self, item_id, name, price, category):
        """Обновить позицию меню"""
        cursor = self.conn.cursor()
        try:
            # Проверяем, не существует ли другой позиции с таким же названием
            cursor.execute('SELECT id FROM menu_items WHERE name = ? AND id != ?', (name, item_id))
            if cursor.fetchone():
                return False, "❌ Позиция с таким названием уже существует"

            cursor.execute(
                'UPDATE menu_items SET name = ?, price = ?, category = ? WHERE id = ?',
                (name, price, category, item_id)
            )
            self.conn.commit()
            return True, "✅ Позиция успешно обновлена"
        except Exception as e:
            return False, f"❌ Ошибка при обновлении: {str(e)}"

    def delete_menu_item(self, item_id):
        """Удалить позицию меню (мягкое удаление - установка is_active = FALSE)"""
        cursor = self.conn.cursor()
        try:
            cursor.execute('UPDATE menu_items SET is_active = FALSE WHERE id = ?', (item_id,))
            self.conn.commit()
            return True, "✅ Позиция успешно удалена"
        except Exception as e:
            return False, f"❌ Ошибка при удалении: {str(e)}"

    def restore_menu_item(self, item_id):
        """Восстановить позицию меню"""
        cursor = self.conn.cursor()
        try:
            cursor.execute('UPDATE menu_items SET is_active = TRUE WHERE id = ?', (item_id,))
            self.conn.commit()
            return True, "✅ Позиция успешно восстановлена"
        except Exception as e:
            return False, f"❌ Ошибка при восстановлении: {str(e)}"

    def get_inactive_menu_items(self):
        """Получить неактивные позиции меню"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT id, name, price, category, is_active 
            FROM menu_items 
            WHERE is_active = FALSE 
            ORDER BY category, name
        ''')
        return cursor.fetchall()

    def add_user(self, telegram_id, first_name, last_name, phone, referred_by=None):
        try:
            cursor = self.conn.cursor()
            registration_date = self.get_moscow_time()

            cursor.execute('''
                INSERT INTO users (telegram_id, first_name, last_name, phone, bonus_balance, referred_by, registration_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (telegram_id, first_name, last_name, phone, 100, referred_by, registration_date))
            user_id = cursor.lastrowid

            # Если пользователь зарегистрирован по реферальной ссылке, создаем запись
            if referred_by:
                cursor.execute('''
                    INSERT INTO referrals (referrer_id, referred_id, created_at)
                    VALUES (?, ?, ?)
                ''', (referred_by, user_id, self.get_moscow_time()))

            self.conn.commit()
            return user_id
        except sqlite3.IntegrityError:
            return None

    def get_user(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        return cursor.fetchone()

    def get_user_by_id(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        return cursor.fetchone()

    def update_user_balance(self, user_id, amount):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET bonus_balance = bonus_balance + ? WHERE id = ?', (amount, user_id))
        self.conn.commit()

    def add_transaction(self, user_id, amount, transaction_type, description):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO transactions (user_id, amount, type, description, date)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, amount, transaction_type, description, self.get_moscow_time()))
        self.conn.commit()

    def create_booking(self, user_id, date, time, guests):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO bookings (user_id, booking_date, booking_time, guests, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, date, time, guests, self.get_moscow_time()))
        self.conn.commit()
        return cursor.lastrowid

    def create_bonus_request(self, user_id, amount):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO bonus_requests (user_id, amount, created_at)
            VALUES (?, ?, ?)
        ''', (user_id, amount, self.get_moscow_time()))
        self.conn.commit()
        return cursor.lastrowid

    def get_all_users(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE is_active = TRUE ORDER BY id DESC')
        return cursor.fetchall()

    def get_pending_requests(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT br.*, u.first_name, u.last_name 
            FROM bonus_requests br 
            JOIN users u ON br.user_id = u.id 
            WHERE br.status = 'pending'
            ORDER BY br.created_at DESC
        ''')
        return cursor.fetchall()

    def update_bonus_request(self, request_id, status):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE bonus_requests SET status = ? WHERE id = ?', (status, request_id))
        self.conn.commit()

    def get_user_bookings(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM bookings WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
        return cursor.fetchall()

    def get_referrer_stats(self, user_id):
        """Получить статистику по рефералам"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as total_referrals, 
                   SUM(CASE WHEN bonus_awarded = 1 THEN 1 ELSE 0 END) as awarded_referrals
            FROM referrals 
            WHERE referrer_id = ?
        ''', (user_id,))
        result = cursor.fetchone()
        return result if result else (0, 0)

    def award_referral_bonus(self, referred_user_id):
        """Начислить бонус рефереру за приглашенного пользователя"""
        cursor = self.conn.cursor()

        # Находим реферера
        cursor.execute('SELECT referred_by FROM users WHERE id = ?', (referred_user_id,))
        result = cursor.fetchone()

        if result and result[0]:
            referrer_id = result[0]

            # Проверяем, не был ли уже начислен бонус
            cursor.execute('''
                SELECT bonus_awarded FROM referrals 
                WHERE referred_id = ? AND referrer_id = ?
            ''', (referred_user_id, referrer_id))

            referral = cursor.fetchone()

            if referral and not referral[0]:
                # Начисляем бонус рефереру
                from config import REFERRAL_BONUS
                self.update_user_balance(referrer_id, REFERRAL_BONUS)
                self.add_transaction(referrer_id, REFERRAL_BONUS, 'earn',
                                     f'Реферальный бонус за приглашенного пользователя')

                # Отмечаем бонус как начисленный
                cursor.execute('''
                    UPDATE referrals SET bonus_awarded = 1 
                    WHERE referred_id = ? AND referrer_id = ?
                ''', (referred_user_id, referrer_id))

                self.conn.commit()
                return referrer_id, REFERRAL_BONUS

        return None, 0

    def get_bookings_by_status(self, status):
        """Получить бронирования по статусу"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT b.*, u.first_name, u.last_name, u.phone, u.telegram_id
            FROM bookings b 
            JOIN users u ON b.user_id = u.id 
            WHERE b.status = ?
            ORDER BY b.booking_date, b.booking_time
        ''', (status,))
        return cursor.fetchall()

    def get_bookings_by_date(self, date):
        """Получить бронирования по дате"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT b.*, u.first_name, u.last_name, u.phone, u.telegram_id
            FROM bookings b 
            JOIN users u ON b.user_id = u.id 
            WHERE b.booking_date = ?
            ORDER BY b.booking_time
        ''', (date,))
        return cursor.fetchall()

    def get_all_bookings_sorted(self):
        """Получить все бронирования с сортировкой по дате и времени"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT b.*, u.first_name, u.last_name, u.phone, u.telegram_id
            FROM bookings b 
            JOIN users u ON b.user_id = u.id 
            ORDER BY b.booking_date, b.booking_time
        ''')
        return cursor.fetchall()

    def get_booking_stats(self):
        """Получить статистику по бронированиям"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT 
                status,
                COUNT(*) as count
            FROM bookings 
            GROUP BY status
        ''')
        stats = cursor.fetchall()

        # Преобразуем в словарь для удобства
        stats_dict = {}
        total = 0
        for status, count in stats:
            stats_dict[status] = count
            total += count

        stats_dict['total'] = total
        return stats_dict

    def get_booking_dates(self):
        """Получить список уникальных дат, на которые есть бронирования"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT DISTINCT booking_date 
            FROM bookings 
            ORDER BY booking_date
        ''')
        dates = cursor.fetchall()
        return [date[0] for date in dates] if dates else []

    def get_order_by_id(self, order_id):
        """Получить заказ по ID"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
        return cursor.fetchone()

    def get_active_orders(self):
        """Получить все активные заказы с информацией об администраторе"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT o.*, u.first_name, u.last_name 
            FROM orders o 
            LEFT JOIN users u ON o.admin_id = u.id 
            WHERE o.status = 'active'
            ORDER BY o.created_at DESC
        ''')
        return cursor.fetchall()

    def get_active_order_by_table(self, table_number):
        """Получить активный заказ по номеру стола"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM orders 
            WHERE table_number = ? AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
        ''', (table_number,))
        return cursor.fetchone()

    def get_orders_by_date(self, date, status=None):
        """Получить заказы по дате с полной информацией"""
        cursor = self.conn.cursor()
        if status:
            cursor.execute('''
                SELECT o.*, u.first_name, u.last_name 
                FROM orders o 
                LEFT JOIN users u ON o.admin_id = u.id 
                WHERE DATE(o.created_at) = ? AND o.status = ?
                ORDER BY o.created_at DESC
            ''', (date, status))
        else:
            cursor.execute('''
                SELECT o.*, u.first_name, u.last_name 
                FROM orders o 
                LEFT JOIN users u ON o.admin_id = u.id 
                WHERE DATE(o.created_at) = ?
                ORDER BY o.created_at DESC
            ''', (date,))
        return cursor.fetchall()

    def get_all_closed_orders(self):
        """Получить все закрытые заказы с информацией об администраторе"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT o.*, u.first_name, u.last_name 
            FROM orders o 
            LEFT JOIN users u ON o.admin_id = u.id 
            WHERE o.status = 'closed'
            ORDER BY o.closed_at DESC
        ''')
        return cursor.fetchall()

    def get_order_dates(self):
        """Получить список уникальных дат, на которые есть заказы"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT DISTINCT DATE(created_at) as order_date 
            FROM orders 
            WHERE status = 'closed'
            ORDER BY order_date DESC
        ''')
        dates = cursor.fetchall()
        return [date[0] for date in dates] if dates else []

    # НОВЫЙ МЕТОД ДЛЯ УДАЛЕНИЯ ПОЗИЦИЙ ИЗ ЗАКАЗА
    def remove_item_from_order(self, order_id, item_name):
        """Удалить позицию из заказа"""
        cursor = self.conn.cursor()

        # Сначала получаем информацию о позиции
        cursor.execute('''
            SELECT id, quantity FROM order_items 
            WHERE order_id = ? AND item_name = ?
        ''', (order_id, item_name))

        item = cursor.fetchone()

        if not item:
            return False, "Позиция не найдена"

        item_id, current_quantity = item

        if current_quantity > 1:
            # Уменьшаем количество
            cursor.execute('''
                UPDATE order_items 
                SET quantity = quantity - 1 
                WHERE id = ?
            ''', (item_id,))
            message = "Количество уменьшено"
        else:
            # Удаляем позицию полностью
            cursor.execute('''
                DELETE FROM order_items 
                WHERE id = ?
            ''', (item_id,))
            message = "Позиция удалена"

        self.conn.commit()
        return True, message

    # НОВЫЙ МЕТОД ДЛЯ ПОЛУЧЕНИЯ ЗАКАЗОВ ЗА СМЕНУ
    def get_orders_by_shift_id(self, shift_id):
        """Получить все заказы конкретной смены"""
        cursor = self.conn.cursor()

        # Получаем информацию о смене
        cursor.execute('SELECT opened_at, closed_at FROM shifts WHERE id = ?', (shift_id,))
        shift_info = cursor.fetchone()

        if not shift_info:
            return []

        opened_at, closed_at = shift_info

        # Если смена закрыта, ищем заказы между opened_at и closed_at
        if closed_at:
            cursor.execute('''
                SELECT * FROM orders 
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY created_at DESC
            ''', (opened_at, closed_at))
        else:
            # Если смена еще открыта, ищем заказы начиная с opened_at
            cursor.execute('''
                SELECT * FROM orders 
                WHERE created_at >= ?
                ORDER BY created_at DESC
            ''', (opened_at,))

        return cursor.fetchall()

    # МЕТОДЫ ДЛЯ УПРАВЛЕНИЯ СМЕНАМИ - ИСПРАВЛЕННЫЕ
    def get_next_shift_number(self, month_year=None):
        """Получить следующий номер смены для указанного месяца"""
        cursor = self.conn.cursor()

        if not month_year:
            month_year = datetime.now().strftime('%Y-%m')

        cursor.execute('''
            SELECT MAX(shift_number) FROM shifts 
            WHERE month_year = ?
        ''', (month_year,))

        result = cursor.fetchone()
        return (result[0] or 0) + 1

    def create_shift(self, admin_id, month_year=None):
        """Создать новую смену - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()

        if not month_year:
            month_year = datetime.now().strftime('%Y-%m')

        shift_number = self.get_next_shift_number(month_year)

        try:
            cursor.execute('''
                INSERT INTO shifts (shift_number, month_year, admin_id, opened_at, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (shift_number, month_year, admin_id, self.get_moscow_time(), 'open'))
            self.conn.commit()
            return shift_number
        except sqlite3.IntegrityError as e:
            # Если возникает ошибка уникальности, пробуем снова с увеличенным номером
            print(f"⚠️ Ошибка уникальности: {e}. Пробуем найти максимальный номер...")
            # Ищем максимальный номер смены для этого месяца
            cursor.execute(''' 
                SELECT shift_number FROM shifts 
                WHERE month_year = ?
                ORDER BY shift_number DESC LIMIT 1
            ''', (month_year,))
            result = cursor.fetchone()

            if result:
                shift_number = result[0] + 1
            else:
                shift_number = 1

            print(f"🔄 Пробуем создать смену с номером {shift_number}")

            try:
                cursor.execute('''
                    INSERT INTO shifts (shift_number, month_year, admin_id, opened_at, status)
                    VALUES (?, ?, ?, ?, ?)
                ''', (shift_number, month_year, admin_id, self.get_moscow_time(), 'open'))
                self.conn.commit()
                return shift_number
            except sqlite3.IntegrityError as e2:
                print(f"❌ Вторая ошибка уникальности: {e2}")
                # Если и это не сработало, ищем свободный номер
                cursor.execute('''
                    SELECT shift_number FROM shifts 
                    WHERE month_year = ?
                    ORDER BY shift_number
                ''', (month_year,))
                existing_shifts = cursor.fetchall()
                existing_numbers = [s[0] for s in existing_shifts]

                # Находим первый свободный номер
                for i in range(1, 1000):  # Максимум 1000 смен в месяце
                    if i not in existing_numbers:
                        shift_number = i
                        break

                cursor.execute('''
                    INSERT INTO shifts (shift_number, month_year, admin_id, opened_at, status)
                    VALUES (?, ?, ?, ?, ?)
                ''', (shift_number, month_year, admin_id, self.get_moscow_time(), 'open'))
                self.conn.commit()
                return shift_number

    def get_active_shift(self):
        """Получить активную смену"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM shifts 
            WHERE status = 'open' 
            ORDER BY opened_at DESC 
            LIMIT 1
        ''')
        return cursor.fetchone()

    def get_shift_by_number_and_month(self, shift_number, month_year):
        """Получить смену по номеру и месяцу"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM shifts 
            WHERE shift_number = ? AND month_year = ?
        ''', (shift_number, month_year))
        return cursor.fetchone()

    def get_shift_by_number(self, shift_number, month_year=None):
        """Получить информацию о смене по номеру"""
        cursor = self.conn.cursor()

        if month_year:
            cursor.execute('SELECT * FROM shifts WHERE shift_number = ? AND month_year = ?',
                           (shift_number, month_year))
        else:
            # Если месяц не указан, ищем последнюю смену с таким номером
            cursor.execute('''
                SELECT * FROM shifts 
                WHERE shift_number = ? 
                ORDER BY month_year DESC, opened_at DESC 
                LIMIT 1
            ''', (shift_number,))

        return cursor.fetchone()

    def close_shift(self, shift_number, month_year, total_revenue, total_orders):
        """Закрыть смену в базе данных - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE shifts 
            SET closed_at = ?, status = 'closed', total_revenue = ?, total_orders = ?
            WHERE shift_number = ? AND month_year = ?
        ''', (self.get_moscow_time(), total_revenue, total_orders, shift_number, month_year))
        self.conn.commit()

    def save_shift_sales(self, shift_number, month_year, sales_data):
        """Сохранить статистику продаж по смене - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()

        # Находим ID смены
        cursor.execute('SELECT id FROM shifts WHERE shift_number = ? AND month_year = ?',
                       (shift_number, month_year))
        shift = cursor.fetchone()

        if not shift:
            print(f"⚠️ Смена #{shift_number} ({month_year}) не найдена")
            return

        shift_id = shift[0]

        # Удаляем старые данные если есть
        cursor.execute('DELETE FROM shift_sales WHERE shift_id = ?', (shift_id,))

        # Сохраняем новые данные
        for item_name, data in sales_data.items():
            cursor.execute('''
                INSERT INTO shift_sales (shift_id, item_name, quantity, total_amount)
                VALUES (?, ?, ?, ?)
            ''', (shift_id, item_name, data['quantity'], data['total_amount']))

        self.conn.commit()

    def get_shift_sales(self, shift_number, month_year):
        """Получить статистику продаж по смене - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()

        # Сначала находим ID смены по номеру и месяцу
        shift = self.get_shift_by_number_and_month(shift_number, month_year)
        if not shift:
            return []

        shift_id = shift[0]

        cursor.execute('''
            SELECT item_name, SUM(quantity) as total_quantity, SUM(total_amount) as total_amount
            FROM shift_sales 
            WHERE shift_id = ?
            GROUP BY item_name
            ORDER BY total_amount DESC
        ''', (shift_id,))
        return cursor.fetchall()

    def get_shift_years(self):
        """Получить список годов, в которых есть смены - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT DISTINCT substr(month_year, 1, 4) as year 
            FROM shifts 
            WHERE status = 'closed'
            ORDER BY year DESC
        ''')
        years = cursor.fetchall()
        return [year[0] for year in years] if years else []

    def get_shift_months(self, year):
        """Получить список месяцев для указанного года - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT DISTINCT substr(month_year, 6, 2) as month 
            FROM shifts 
            WHERE substr(month_year, 1, 4) = ? AND status = 'closed'
            ORDER BY month DESC
        ''', (year,))
        months = cursor.fetchall()
        return [month[0] for month in months] if months else []

    def get_shifts_by_year_month(self, year, month):
        """Получить список смен для указанного года и месяца - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()
        month_year = f"{year}-{month:02d}" if isinstance(month, int) else f"{year}-{month}"

        cursor.execute('''
            SELECT * FROM shifts 
            WHERE month_year = ? AND status = 'closed'
            ORDER BY shift_number DESC
        ''', (month_year,))
        return cursor.fetchall()

    def get_all_shifts_sorted(self):
        """Получить все смены с сортировкой по дате"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM shifts 
            WHERE status = 'closed'
            ORDER BY month_year DESC, shift_number DESC
        ''')
        return cursor.fetchall()

    def get_shifts_by_period(self, period='all'):
        """Получить смены за период"""
        cursor = self.conn.cursor()

        if period == 'month':
            start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT * FROM shifts 
                WHERE DATE(opened_at) >= ? AND status = 'closed'
                ORDER BY month_year DESC, shift_number DESC
            ''', (start_date,))
        elif period == 'year':
            start_date = datetime.now().replace(month=1, day=1).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT * FROM shifts 
                WHERE DATE(opened_at) >= ? AND status = 'closed'
                ORDER BY month_year DESC, shift_number DESC
            ''', (start_date,))
        else:
            cursor.execute('''
                SELECT * FROM shifts 
                WHERE status = 'closed'
                ORDER BY month_year DESC, shift_number DESC
            ''')
        return cursor.fetchall()

    def get_sales_statistics_by_period(self, period):
        """Получить статистику продаж за период"""
        cursor = self.conn.cursor()

        if period == 'month':
            start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT ss.item_name, SUM(ss.quantity) as total_quantity, SUM(ss.total_amount) as total_amount
                FROM shift_sales ss
                JOIN shifts s ON ss.shift_id = s.id
                WHERE DATE(s.opened_at) >= ? AND s.status = 'closed'
                GROUP BY ss.item_name
                ORDER BY total_amount DESC
            ''', (start_date,))
        elif period == 'year':
            start_date = datetime.now().replace(month=1, day=1).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT ss.item_name, SUM(ss.quantity) as total_quantity, SUM(ss.total_amount) as total_amount
                FROM shift_sales ss
                JOIN shifts s ON ss.shift_id = s.id
                WHERE DATE(s.opened_at) >= ? AND s.status = 'closed'
                GROUP BY ss.item_name
                ORDER BY total_amount DESC
            ''', (start_date,))
        else:
            cursor.execute('''
                SELECT ss.item_name, SUM(ss.quantity) as total_quantity, SUM(ss.total_amount) as total_amount
                FROM shift_sales ss
                JOIN shifts s ON ss.shift_id = s.id
                WHERE s.status = 'closed'
                GROUP BY ss.item_name
                ORDER BY total_amount DESC
            ''')
        return cursor.fetchall()

    def get_total_revenue_by_period(self, period):
        """Получить общую выручку за период"""
        cursor = self.conn.cursor()

        if period == 'month':
            start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT SUM(total_revenue) FROM shifts 
                WHERE DATE(opened_at) >= ? AND status = 'closed'
            ''', (start_date,))
        elif period == 'year':
            start_date = datetime.now().replace(month=1, day=1).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT SUM(total_revenue) FROM shifts 
                WHERE DATE(opened_at) >= ? AND status = 'closed'
            ''', (start_date,))
        else:
            cursor.execute('SELECT SUM(total_revenue) FROM shifts WHERE status = "closed"')

        result = cursor.fetchone()
        return result[0] or 0

    # НОВЫЕ МЕТОДЫ ДЛЯ СТАТИСТИКИ ПО ГОДАМ И МЕСЯЦАМ
    def get_sales_statistics_by_year(self, year):
        """Получить статистику продаж за указанный год - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT ss.item_name, SUM(ss.quantity) as total_quantity, SUM(ss.total_amount) as total_amount
            FROM shift_sales ss
            JOIN shifts s ON ss.shift_id = s.id
            WHERE substr(s.month_year, 1, 4) = ? AND s.status = 'closed'
            GROUP BY ss.item_name
            ORDER BY total_amount DESC
        ''', (year,))
        return cursor.fetchall()

    def get_total_revenue_by_year(self, year):
        """Получить общую выручку за указанный год - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT SUM(total_revenue) FROM shifts 
            WHERE substr(month_year, 1, 4) = ? AND status = 'closed'
        ''', (year,))
        result = cursor.fetchone()
        return result[0] or 0

    def get_sales_statistics_by_year_month(self, year, month):
        """Получить статистику продаж за указанный год и месяц - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()
        month_year = f"{year}-{month:02d}" if isinstance(month, int) else f"{year}-{month}"

        cursor.execute('''
            SELECT ss.item_name, SUM(ss.quantity) as total_quantity, SUM(ss.total_amount) as total_amount
            FROM shift_sales ss
            JOIN shifts s ON ss.shift_id = s.id
            WHERE s.month_year = ? AND s.status = 'closed'
            GROUP BY ss.item_name
            ORDER BY total_amount DESC
        ''', (month_year,))
        return cursor.fetchall()

    def get_total_revenue_by_year_month(self, year, month):
        """Получить общую выручку за указанный год и месяц - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        cursor = self.conn.cursor()
        month_year = f"{year}-{month:02d}" if isinstance(month, int) else f"{year}-{month}"

        cursor.execute('''
            SELECT SUM(total_revenue) FROM shifts 
            WHERE month_year = ? AND status = 'closed'
        ''', (month_year,))
        result = cursor.fetchone()
        return result[0] or 0

    def get_all_shifts(self):
        """Получить все смены с сортировкой по дате открытия"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM shifts 
            ORDER BY opened_at DESC
        ''')
        return cursor.fetchall()

    def get_shifts_by_month(self, month_year):
        """Получить смены за указанный месяц"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM shifts 
            WHERE month_year = ? 
            ORDER BY shift_number ASC
        ''', (month_year,))
        return cursor.fetchall()

    # НОВЫЕ МЕТОДЫ ДЛЯ ОТЛАДКИ
    def get_all_shifts_debug(self):
        """Для отладки - получить все смены с деталями"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT id, shift_number, month_year, opened_at, closed_at, 
                   total_revenue, total_orders, status
            FROM shifts 
            ORDER BY month_year DESC, shift_number DESC
        ''')
        return cursor.fetchall()

    def get_current_month_year(self):
        """Получить текущий месяц и год"""
        return datetime.now().strftime('%Y-%m')

    # НОВЫЕ МЕТОДЫ ДЛЯ ПОДСЧЕТА СПИСАННЫХ БОНУСОВ
    def get_spent_bonuses_by_shift(self, shift_number, month_year):
        """Получить сумму списанных бонусов за смену"""
        cursor = self.conn.cursor()

        # Находим ID смены
        shift = self.get_shift_by_number_and_month(shift_number, month_year)
        if not shift:
            return 0

        shift_id = shift[0]
        opened_at, closed_at = shift[4], shift[5]

        if closed_at:
            cursor.execute('''
                SELECT SUM(amount) 
                FROM transactions 
                WHERE type = 'spend' 
                AND date >= ? AND date <= ?
            ''', (opened_at, closed_at))
        else:
            cursor.execute('''
                SELECT SUM(amount) 
                FROM transactions 
                WHERE type = 'spend' 
                AND date >= ?
            ''', (opened_at,))

        result = cursor.fetchone()
        return result[0] or 0

    def get_spent_bonuses_by_month(self, year, month):
        """Получить сумму списанных бонусов за месяц"""
        cursor = self.conn.cursor()

        # Формируем строку месяца: YYYY-MM
        if isinstance(month, int):
            month_str = f"{year}-{month:02d}"
        else:
            month_str = f"{year}-{month}"

        cursor.execute('''
            SELECT SUM(amount) 
            FROM transactions 
            WHERE type = 'spend' 
            AND strftime('%Y-%m', date) = ?
        ''', (month_str,))

        result = cursor.fetchone()
        return result[0] or 0

    def get_spent_bonuses_by_year(self, year):
        """Получить сумму списанных бонусов за год"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT SUM(amount) 
            FROM transactions 
            WHERE type = 'spend' 
            AND strftime('%Y', date) = ?
        ''', (year,))

        result = cursor.fetchone()
        return result[0] or 0

    def get_spent_bonuses_by_period(self, period):
        """Получить сумму списанных бонусов за период (month/year)"""
        cursor = self.conn.cursor()

        if period == 'month':
            start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT SUM(amount) 
                FROM transactions 
                WHERE type = 'spend' 
                AND date >= ?
            ''', (start_date,))
        elif period == 'year':
            start_date = datetime.now().replace(month=1, day=1).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT SUM(amount) 
                FROM transactions 
                WHERE type = 'spend' 
                AND date >= ?
            ''', (start_date,))
        else:
            cursor.execute('SELECT SUM(amount) FROM transactions WHERE type = "spend"')

        result = cursor.fetchone()
        return result[0] or 0

    # ========== ДОБАВЬТЕ ЭТИ 2 НОВЫХ МЕТОДА ЗДЕСЬ ==========

    def get_payment_statistics_by_month(self, year, month):
        """Получить статистику по оплате за месяц"""
        cursor = self.conn.cursor()
        month_year = f"{year}-{month:02d}" if isinstance(month, int) else f"{year}-{month}"

        cursor.execute('''
            SELECT o.payment_method, COUNT(*) as count, SUM(total) as total_amount
            FROM (
                SELECT o.id, o.payment_method, 
                       SUM(oi.price * oi.quantity) as total
                FROM orders o
                LEFT JOIN order_items oi ON o.id = oi.order_id
                WHERE strftime('%Y-%m', o.created_at) = ? 
                    AND o.status = 'closed'
                    AND o.payment_method IS NOT NULL
                GROUP BY o.id
            ) o
            GROUP BY o.payment_method
        ''', (month_year,))

        stats = {}
        for payment_method, count, total_amount in cursor.fetchall():
            stats[payment_method] = {'count': count, 'total_amount': total_amount or 0}

        return stats

    def get_payment_statistics_by_year(self, year):
        """Получить статистику по оплате за год"""
        cursor = self.conn.cursor()

        cursor.execute('''
            SELECT o.payment_method, COUNT(*) as count, SUM(total) as total_amount
            FROM (
                SELECT o.id, o.payment_method, 
                       SUM(oi.price * oi.quantity) as total
                FROM orders o
                LEFT JOIN order_items oi ON o.id = oi.order_id
                WHERE strftime('%Y', o.created_at) = ? 
                    AND o.status = 'closed'
                    AND o.payment_method IS NOT NULL
                GROUP BY o.id
            ) o
            GROUP BY o.payment_method
        ''', (year,))

        stats = {}
        for payment_method, count, total_amount in cursor.fetchall():
            stats[payment_method] = {'count': count, 'total_amount': total_amount or 0}

        return stats

    # ========== ДОБАВЬТЕ ЭТИ МЕТОДЫ ЗДЕСЬ ==========

    def add_payment_method_column(self):
        """Добавить колонку payment_method в таблицу orders если её нет"""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(orders)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'payment_method' not in columns:
            print("🔄 Добавляем колонку payment_method в таблицу orders...")
            cursor.execute('ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT NULL')
            self.conn.commit()
            print("✅ Колонка payment_method добавлена")
            return True
        print("✅ Колонка payment_method уже существует")
        return False

    def update_order_payment_method(self, order_id, payment_method):
        """Обновить метод оплаты для заказа"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE orders SET payment_method = ? WHERE id = ?
        ''', (payment_method, order_id))
        self.conn.commit()

    def get_payment_statistics_by_shift(self, shift_number, month_year):
        """Получить статистику по оплате за смену"""
        cursor = self.conn.cursor()

        # Находим ID смены
        shift = self.get_shift_by_number_and_month(shift_number, month_year)
        if not shift:
            return {}

        shift_id = shift[0]
        opened_at, closed_at = shift[4], shift[5]

        if closed_at:
            cursor.execute('''
                SELECT o.payment_method, COUNT(*) as count, SUM(total) as total_amount
                FROM (
                    SELECT o.id, o.payment_method, 
                           SUM(oi.price * oi.quantity) as total
                    FROM orders o
                    LEFT JOIN order_items oi ON o.id = oi.order_id
                    WHERE o.created_at >= ? AND o.created_at <= ? 
                        AND o.status = 'closed'
                        AND o.payment_method IS NOT NULL
                    GROUP BY o.id
                ) o
                GROUP BY o.payment_method
            ''', (opened_at, closed_at))
        else:
            cursor.execute('''
                SELECT o.payment_method, COUNT(*) as count, SUM(total) as total_amount
                FROM (
                    SELECT o.id, o.payment_method, 
                           SUM(oi.price * oi.quantity) as total
                    FROM orders o
                    LEFT JOIN order_items oi ON o.id = oi.order_id
                    WHERE o.created_at >= ? 
                        AND o.status = 'closed'
                        AND o.payment_method IS NOT NULL
                    GROUP BY o.id
                ) o
                GROUP BY o.payment_method
            ''', (opened_at,))

        stats = {}
        for payment_method, count, total_amount in cursor.fetchall():
            stats[payment_method] = {'count': count, 'total_amount': total_amount or 0}

        return stats

    def get_payment_statistics_by_period(self, period):
        """Получить статистику по оплате за период"""
        cursor = self.conn.cursor()

        if period == 'month':
            start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT o.payment_method, COUNT(*) as count, SUM(total) as total_amount
                FROM (
                    SELECT o.id, o.payment_method, 
                           SUM(oi.price * oi.quantity) as total
                    FROM orders o
                    LEFT JOIN order_items oi ON o.id = oi.order_id
                    WHERE o.created_at >= ? 
                        AND o.status = 'closed'
                        AND o.payment_method IS NOT NULL
                    GROUP BY o.id
                ) o
                GROUP BY o.payment_method
            ''', (start_date,))
        elif period == 'year':
            start_date = datetime.now().replace(month=1, day=1).strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT o.payment_method, COUNT(*) as count, SUM(total) as total_amount
                FROM (
                    SELECT o.id, o.payment_method, 
                           SUM(oi.price * oi.quantity) as total
                    FROM orders o
                    LEFT JOIN order_items oi ON o.id = oi.order_id
                    WHERE o.created_at >= ? 
                        AND o.status = 'closed'
                        AND o.payment_method IS NOT NULL
                    GROUP BY o.id
                ) o
                GROUP BY o.payment_method
            ''', (start_date,))
        else:
            cursor.execute('''
                SELECT o.payment_method, COUNT(*) as count, SUM(total) as total_amount
                FROM (
                    SELECT o.id, o.payment_method, 
                           SUM(oi.price * oi.quantity) as total
                    FROM orders o
                    LEFT JOIN order_items oi ON o.id = oi.order_id
                    WHERE o.status = 'closed'
                        AND o.payment_method IS NOT NULL
                    GROUP BY o.id
                ) o
                GROUP BY o.payment_method
            ''')

        stats = {}
        for payment_method, count, total_amount in cursor.fetchall():
            stats[payment_method] = {'count': count, 'total_amount': total_amount or 0}

        return stats