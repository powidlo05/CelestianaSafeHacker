import sqlite3


class Database:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "user_id INTEGER PRIMARY KEY, "
            "added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        # миграция старой БД: колонка с ником
        cols = [row[1] for row in self.conn.execute("PRAGMA table_info(users)")]
        if "username" not in cols:
            self.conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
        self.conn.commit()

    def is_authorized(self, user_id: int) -> bool:
        cur = self.conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return cur.fetchone() is not None

    def add_user(self, user_id: int, username: str | None = None) -> tuple[bool, str]:
        if self.is_authorized(user_id):
            return False, f"⚠️ Пользователь <code>{user_id}</code> УЖЕ есть в списке."
        self.conn.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        self.conn.commit()
        return True, f"✅ Пользователь <code>{user_id}</code> добавлен."

    def remove_user(self, user_id: int) -> tuple[bool, str]:
        if not self.is_authorized(user_id):
            return False, f"⚠️ Пользователя <code>{user_id}</code> НЕТ в списке."
        self.conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        self.conn.commit()
        return True, f"✅ Пользователь <code>{user_id}</code> удалён."

    def update_username(self, user_id: int, username: str | None) -> None:
        """Обновляет ник, если пользователь есть в БД."""
        if username is None:
            return
        self.conn.execute(
            "UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        self.conn.commit()

    def get_all_users(self) -> list[tuple[int, str | None]]:
        cur = self.conn.execute("SELECT user_id, username FROM users")
        return cur.fetchall()