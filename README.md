# 🏋️ Fitness Center Manager

A Python desktop application for managing gym members, trainers, and sessions with role-based login and a SQLite backend.

---

## Features

- **Role-based login** — separate panels for Admins, Members, and Trainers
- **Admin panel** — create and manage group/PT sessions, assign trainers, manage branches and studios
- **Member panel** — browse and reserve sessions, view schedule, manage profile
- **Trainer panel** — view schedule, create/modify/delete PT sessions, update specialties and hourly fee
- **Conflict detection** — prevents double-booking of studios and trainers
- **SQLite backend** — lightweight, file-based database with foreign key support

---

## Requirements

- Python 3.8+
- [FreeSimpleGUI](https://pypi.org/project/FreeSimpleGUI/)

Install dependencies:

```bash
pip install FreeSimpleGUI
```

---

## Setup

1. **Clone the repository:**

```bash
git clone https://github.com/ulassakin/fitness-center-app.git
cd fitness-center-app
```

2. **Set up the database:**

Make sure your SQLite database file is available. Update the `DB_PATH` variable at the top of `fitness_fixed.py` to point to your database file:

```python
DB_PATH = "path/to/your/database.db"
```

3. **Run the application:**

```bash
python fitness_fixed.py
```

---

## Database Schema

The application expects the following tables in your SQLite database:

| Table | Description |
|---|---|
| `User` | All users (email, name, surname, password, gender) |
| `Admin` | Admin accounts |
| `Member` | Member accounts (age, height, weight) |
| `Trainer` | Trainer accounts (hourly fee) |
| `Trainer_Specialty` | Trainer specialties |
| `Branch` | Gym branches |
| `StudioHasBranch` | Studios per branch with capacity |
| `SessionWithBranch` | All sessions (group and PT) |
| `Trains_Group` | Group session assignments |
| `PT_Session_Trains` | PT session assignments |
| `Reserves` | Member reservations |

---

## Project Structure

```
fitness-center-app/
├── fitness_fixed.py   # Main application file
├── README.md
└── .gitignore
```

---

## Notes

- Passwords are stored in plaintext in the current version. For production use, consider hashing passwords with `bcrypt` or `hashlib`.
- The `.db` database file is excluded from the repository via `.gitignore`. You will need to provide or initialize your own database.

---

## License

This project is open source and available under the [MIT License](LICENSE).
