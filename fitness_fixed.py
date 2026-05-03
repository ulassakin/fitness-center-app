import sqlite3
from datetime import datetime

try:
    import FreeSimpleGUI as sg
except ImportError as e:
    raise SystemExit(
        "FreeSimpleGUI is not installed. Install it with: pip install FreeSimpleGUI\n"
        "Then run this script again."
    ) from e

DB_PATH = r"C:\Users\ulass\Downloads\Algorithm_final\Algorithm_f.db"
DATETIME_FMT = '%Y-%m-%d %H:%M'
DB_DATETIME_FMT = '%Y-%m-%d %H:%M:%S'


class FitnessCenterGUIApp:
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.cur = self.conn.cursor()
        self.cur.execute('PRAGMA foreign_keys = ON')

    # -------------------- generic db helpers --------------------
    def fetchone(self, query, params=()):
        self.cur.execute(query, params)
        return self.cur.fetchone()

    def fetchall(self, query, params=()):
        self.cur.execute(query, params)
        return self.cur.fetchall()

    def execute(self, query, params=()):
        self.cur.execute(query, params)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # -------------------- shared utilities --------------------
    def user_exists(self, email):
        return self.fetchone('SELECT 1 FROM User WHERE Email = ?', (email,)) is not None

    def get_user_roles(self, email):
        roles = []
        if self.fetchone('SELECT 1 FROM Admin WHERE AEmail = ?', (email,)):
            roles.append('admin')
        if self.fetchone('SELECT 1 FROM Member WHERE MEmail = ?', (email,)):
            roles.append('member')
        if self.fetchone('SELECT 1 FROM Trainer WHERE TEmail = ?', (email,)):
            roles.append('trainer')
        return roles

    def login(self, email, password, role):
        user = self.fetchone('SELECT * FROM User WHERE Email = ? AND Pass = ?', (email, password))
        if not user:
            return False, 'Invalid email or password.'
        if role not in self.get_user_roles(email):
            return False, f'This account is not registered as a {role}.'
        return True, f'Welcome, {user["Name"]} {user["Surname"]}!'

    def parse_user_datetime(self, value):
        return datetime.strptime(value.strip(), DATETIME_FMT)

    def times_overlap(self, start1, end1, start2, end2):
        return start1 < end2 and start2 < end1

    def next_session_id(self):
        row = self.fetchone('SELECT COALESCE(MAX(SessionNo), 1000) + 1 AS NextId FROM SessionWithBranch')
        return int(row['NextId'])

    # -------------------- member signup --------------------
    def create_member_account(self, data):
        email = data['email'].strip()
        name = data['name'].strip()
        surname = data['surname'].strip()
        password = data['password']
        gender = data['gender'].strip()

        if not all([email, name, surname, password, gender]):
            return False, 'Please fill in all required fields.'
        if self.user_exists(email):
            return False, 'This email already exists.'

        try:
            age = int(data['age'])
            height = float(data['height'])
            weight = float(data['weight'])
        except ValueError:
            return False, 'Age must be an integer. Height and weight must be numeric.'

        self.execute(
            'INSERT INTO User (Email, Name, Surname, Pass, Gender) VALUES (?, ?, ?, ?, ?)',
            (email, name, surname, password, gender)
        )
        self.execute(
            'INSERT INTO Member (MEmail, Age, Height, Weight) VALUES (?, ?, ?, ?)',
            (email, age, height, weight)
        )
        return True, 'Member account created successfully.'

    # -------------------- admin workflow --------------------
    def get_branches(self):
        return self.fetchall('SELECT Name, Adress FROM Branch ORDER BY Name')

    def get_studios_for_branch(self, branch_name):
        return self.fetchall(
            'SELECT StudioNumber, Capacity FROM StudioHasBranch WHERE SName = ? ORDER BY StudioNumber',
            (branch_name,)
        )

    def get_eligible_trainers(self, exercise_type):
        return self.fetchall(
            '''
            SELECT t.TEmail, u.Name, u.Surname,
                   GROUP_CONCAT(ts.Specialty, ', ') AS Specialties, t.Hourly_Fee
            FROM Trainer t
            JOIN User u ON u.Email = t.TEmail
            JOIN Trainer_Specialty ts ON ts.TEmail = t.TEmail
            WHERE LOWER(ts.Specialty) LIKE ?
            GROUP BY t.TEmail, u.Name, u.Surname, t.Hourly_Fee
            ORDER BY u.Name, u.Surname
            ''',
            (f'%{exercise_type.lower()}%',)
        )

    def get_all_trainers(self):
        return self.fetchall(
            '''
            SELECT t.TEmail, u.Name, u.Surname,
                   GROUP_CONCAT(ts.Specialty, ', ') AS Specialties, t.Hourly_Fee
            FROM Trainer t
            JOIN User u ON u.Email = t.TEmail
            LEFT JOIN Trainer_Specialty ts ON ts.TEmail = t.TEmail
            GROUP BY t.TEmail, u.Name, u.Surname, t.Hourly_Fee
            ORDER BY u.Name, u.Surname
            '''
        )

    def studio_has_conflict(self, studio_number, start_dt, end_dt, exclude_session_no=None):
        rows = self.fetchall(
            '''
            SELECT swb.StartTime, swb.EndTime, swb.SessionNo
            FROM Trains_Group tg
            JOIN SessionWithBranch swb ON swb.SessionNo = tg.GSessionNo
            WHERE tg.StudioNumber = ?
            ''',
            (studio_number,)
        )
        for row in rows:
            if exclude_session_no and row['SessionNo'] == exclude_session_no:
                continue
            existing_start = datetime.fromisoformat(row['StartTime'])
            existing_end = datetime.fromisoformat(row['EndTime'])
            if self.times_overlap(start_dt, end_dt, existing_start, existing_end):
                return True

        studio_branch = self.fetchone(
            'SELECT SName FROM StudioHasBranch WHERE StudioNumber = ?', (studio_number,)
        )
        if studio_branch:
            branch_sessions = self.fetchall(
                '''
                SELECT swb.StartTime, swb.EndTime, swb.SessionNo
                FROM SessionWithBranch swb
                WHERE swb.BName = ?
                  AND swb.SessionNo NOT IN (
                      SELECT GSessionNo FROM Trains_Group WHERE StudioNumber = ?
                  )
                ''',
                (studio_branch['SName'], studio_number)
            )
            for row in branch_sessions:
                if exclude_session_no and row['SessionNo'] == exclude_session_no:
                    continue
                existing_start = datetime.fromisoformat(row['StartTime'])
                existing_end = datetime.fromisoformat(row['EndTime'])
                if self.times_overlap(start_dt, end_dt, existing_start, existing_end):
                    return True

        return False

    def trainer_has_conflict(self, trainer_email, start_dt, end_dt, exclude_session_no=None):
        rows = self.fetchall(
            '''
            SELECT swb.StartTime, swb.EndTime, swb.SessionNo
            FROM Trains_Group tg
            JOIN SessionWithBranch swb ON swb.SessionNo = tg.GSessionNo
            WHERE tg.TrEmail = ?
            UNION ALL
            SELECT swb.StartTime, swb.EndTime, swb.SessionNo
            FROM PT_Session_Trains pt
            JOIN SessionWithBranch swb ON swb.SessionNo = pt.SessionNo
            WHERE pt.TEmail = ?
            ''',
            (trainer_email, trainer_email)
        )
        for row in rows:
            if exclude_session_no and row['SessionNo'] == exclude_session_no:
                continue
            existing_start = datetime.fromisoformat(row['StartTime'])
            existing_end = datetime.fromisoformat(row['EndTime'])
            if self.times_overlap(start_dt, end_dt, existing_start, existing_end):
                return True
        return False

    def create_group_session(self, branch_name, studio_number, trainer_email, exercise_type, start_text, end_text):
        if not all([branch_name, exercise_type, start_text, end_text]):
            return False, 'Please fill in all session fields.'

        branch = self.fetchone('SELECT 1 FROM Branch WHERE Name = ?', (branch_name,))
        if not branch:
            return False, 'Invalid branch.'

        try:
            studio_number = int(studio_number)
        except ValueError:
            return False, 'Studio number must be numeric.'

        studio = self.fetchone(
            'SELECT 1 FROM StudioHasBranch WHERE SName = ? AND StudioNumber = ?',
            (branch_name, studio_number)
        )
        if not studio:
            return False, 'Selected studio does not belong to the chosen branch.'

        try:
            start_dt = self.parse_user_datetime(start_text)
            end_dt = self.parse_user_datetime(end_text)
        except ValueError:
            return False, f'Datetime format must be {DATETIME_FMT}.'

        if end_dt <= start_dt:
            return False, 'End time must be later than start time.'

        day_of_week = start_dt.strftime('%Y-%m-%d')

        eligible_trainers = self.get_eligible_trainers(exercise_type)
        if not eligible_trainers:
            return False, 'No trainer matches this exercise type.'

        valid_trainer = any(r['TEmail'] == trainer_email for r in eligible_trainers)
        if not valid_trainer:
            return False, 'Selected trainer is not eligible for this exercise type.'

        if self.studio_has_conflict(studio_number, start_dt, end_dt):
            return False, 'Conflict detected: studio is not available at that time.'

        if self.trainer_has_conflict(trainer_email, start_dt, end_dt):
            return False, 'Conflict detected: trainer is not available at that time.'

        session_no = self.next_session_id()
        self.execute(
            'INSERT INTO SessionWithBranch (BName, SessionNo, DayOfWeek, StartTime, EndTime) VALUES (?, ?, ?, ?, ?)',
            (branch_name, session_no, day_of_week,
             start_dt.strftime(DB_DATETIME_FMT), end_dt.strftime(DB_DATETIME_FMT))
        )
        self.execute(
            'INSERT INTO GroupSession (GSessionNo, ExerciseType) VALUES (?, ?)',
            (session_no, exercise_type)
        )
        self.execute(
            'INSERT INTO Trains_Group (TrEmail, StudioNumber, GSessionNo) VALUES (?, ?, ?)',
            (trainer_email, studio_number, session_no)
        )
        return True, f'Group session created successfully. Assigned Session ID: {session_no}'

    def create_pt_session(self, branch_name, trainer_email, start_text, end_text):
        """Create a Personal Training session (admin creates)."""
        if not all([branch_name, trainer_email, start_text, end_text]):
            return False, 'Please fill in all PT session fields.'

        branch = self.fetchone('SELECT 1 FROM Branch WHERE Name = ?', (branch_name,))
        if not branch:
            return False, 'Invalid branch.'

        try:
            start_dt = self.parse_user_datetime(start_text)
            end_dt = self.parse_user_datetime(end_text)
        except ValueError:
            return False, f'Datetime format must be {DATETIME_FMT}.'

        if end_dt <= start_dt:
            return False, 'End time must be later than start time.'

        day_of_week = start_dt.strftime('%Y-%m-%d')

        if self.trainer_has_conflict(trainer_email, start_dt, end_dt):
            return False, 'Conflict detected: trainer is not available at that time.'

        session_no = self.next_session_id()
        self.execute(
            'INSERT INTO SessionWithBranch (BName, SessionNo, DayOfWeek, StartTime, EndTime) VALUES (?, ?, ?, ?, ?)',
            (branch_name, session_no, day_of_week,
             start_dt.strftime(DB_DATETIME_FMT), end_dt.strftime(DB_DATETIME_FMT))
        )
        self.execute(
            'INSERT INTO PT_Session_Trains (SessionNo, TEmail) VALUES (?, ?)',
            (session_no, trainer_email)
        )
        return True, f'PT session created successfully. Assigned Session ID: {session_no}'

    # -------------------- trainer self-service PT management (Text 2) --------------------
    def trainer_create_pt_session(self, trainer_email, branch_name, start_text, end_text):
        """Trainer creates their own PT session."""
        if not all([branch_name, start_text, end_text]):
            return False, 'Please fill in all PT session fields.'

        branch = self.fetchone('SELECT 1 FROM Branch WHERE Name = ?', (branch_name,))
        if not branch:
            return False, 'Invalid branch.'

        try:
            start_dt = self.parse_user_datetime(start_text)
            end_dt = self.parse_user_datetime(end_text)
        except ValueError:
            return False, f'Datetime format must be {DATETIME_FMT}.'

        if end_dt <= start_dt:
            return False, 'End time must be later than start time.'

        day_of_week = start_dt.strftime('%Y-%m-%d')

        if self.trainer_has_conflict(trainer_email, start_dt, end_dt):
            return False, 'Conflict detected: this time overlaps with your existing group or PT sessions.'

        session_no = self.next_session_id()
        self.execute(
            'INSERT INTO SessionWithBranch (BName, SessionNo, DayOfWeek, StartTime, EndTime) VALUES (?, ?, ?, ?, ?)',
            (branch_name, session_no, day_of_week,
             start_dt.strftime(DB_DATETIME_FMT), end_dt.strftime(DB_DATETIME_FMT))
        )
        self.execute(
            'INSERT INTO PT_Session_Trains (SessionNo, TEmail) VALUES (?, ?)',
            (session_no, trainer_email)
        )
        return True, f'PT session created successfully. Session ID: {session_no}'

    def trainer_modify_pt_session(self, trainer_email, session_no, new_branch, new_start_text, new_end_text):
        """Trainer modifies an existing PT session."""
        owns = self.fetchone(
            'SELECT 1 FROM PT_Session_Trains WHERE TEmail = ? AND SessionNo = ?',
            (trainer_email, session_no)
        )
        if not owns:
            return False, 'You do not own this PT session.'

        reserved = self.fetchone('SELECT 1 FROM Reserves WHERE SessionNo = ?', (session_no,))

        if not all([new_branch, new_start_text, new_end_text]):
            return False, 'Please fill in all fields.'

        branch = self.fetchone('SELECT 1 FROM Branch WHERE Name = ?', (new_branch,))
        if not branch:
            return False, 'Invalid branch.'

        try:
            start_dt = self.parse_user_datetime(new_start_text)
            end_dt = self.parse_user_datetime(new_end_text)
        except ValueError:
            return False, f'Datetime format must be {DATETIME_FMT}.'

        if end_dt <= start_dt:
            return False, 'End time must be later than start time.'

        day_of_week = start_dt.strftime('%Y-%m-%d')

        if self.trainer_has_conflict(trainer_email, start_dt, end_dt, exclude_session_no=session_no):
            return False, 'Conflict detected: new time overlaps with your existing sessions.'

        self.execute(
            'UPDATE SessionWithBranch SET BName = ?, DayOfWeek = ?, StartTime = ?, EndTime = ? WHERE SessionNo = ?',
            (new_branch, day_of_week,
             start_dt.strftime(DB_DATETIME_FMT), end_dt.strftime(DB_DATETIME_FMT), session_no)
        )
        msg = f'PT session {session_no} updated successfully.'
        if reserved:
            msg += ' (Note: a member has already reserved this session.)'
        return True, msg

    def trainer_delete_pt_session(self, trainer_email, session_no):
        """Trainer deletes a PT session they own."""
        owns = self.fetchone(
            'SELECT 1 FROM PT_Session_Trains WHERE TEmail = ? AND SessionNo = ?',
            (trainer_email, session_no)
        )
        if not owns:
            return False, 'You do not own this PT session.'

        self.execute('DELETE FROM Reserves WHERE SessionNo = ?', (session_no,))
        rate_rows = self.fetchall('SELECT RNumber FROM Rates WHERE SessionNo = ?', (session_no,))
        for r in rate_rows:
            self.execute('DELETE FROM Rating WHERE RNumber = ?', (r['RNumber'],))
        self.execute('DELETE FROM Rates WHERE SessionNo = ?', (session_no,))
        self.execute('DELETE FROM PT_Session_Trains WHERE SessionNo = ?', (session_no,))
        self.execute('DELETE FROM SessionWithBranch WHERE SessionNo = ?', (session_no,))
        return True, f'PT session {session_no} deleted successfully.'

    def update_trainer_hourly_fee(self, trainer_email, new_fee_text):
        """Update the trainer's hourly fee."""
        try:
            new_fee = float(new_fee_text)
            if new_fee < 0:
                raise ValueError
        except ValueError:
            return False, 'Hourly fee must be a non-negative number.'
        self.execute('UPDATE Trainer SET Hourly_Fee = ? WHERE TEmail = ?', (new_fee, trainer_email))
        return True, f'Hourly fee updated to {new_fee}.'

    def update_trainer_specialties(self, trainer_email, new_specialties):
        """Update the trainer's specialties."""
        if not new_specialties.strip():
            return False, 'Specialties cannot be empty.'
        specialties = [s.strip() for s in new_specialties.split(',') if s.strip()]
        if not specialties:
            return False, 'Specialties cannot be empty.'
        self.execute('DELETE FROM Trainer_Specialty WHERE TEmail = ?', (trainer_email,))
        for specialty in specialties:
            self.execute(
                'INSERT INTO Trainer_Specialty (TEmail, Specialty) VALUES (?, ?)',
                (trainer_email, specialty)
            )
        return True, f'Specialties updated to: {", ".join(specialties)}'

    def get_trainer_info(self, trainer_email):
        """Get trainer profile information."""
        return self.fetchone(
            '''
            SELECT t.TEmail, u.Name, u.Surname, u.Gender,
                   GROUP_CONCAT(ts.Specialty, ', ') AS Specialties, t.Hourly_Fee
            FROM Trainer t
            JOIN User u ON u.Email = t.TEmail
            LEFT JOIN Trainer_Specialty ts ON ts.TEmail = t.TEmail
            WHERE t.TEmail = ?
            GROUP BY t.TEmail, u.Name, u.Surname, u.Gender, t.Hourly_Fee
            ''',
            (trainer_email,)
        )

    # -------------------- member workflow --------------------
    def get_group_sessions(self, branch_filter='', exercise_filter='', day_filter=''):
        query = '''
            SELECT
                gs.GSessionNo AS SessionNo,
                gs.ExerciseType,
                swb.BName,
                swb.DayOfWeek,
                swb.StartTime,
                swb.EndTime,
                tg.StudioNumber,
                shb.Capacity,
                u.Name || ' ' || u.Surname AS TrainerName,
                t.TEmail,
                GROUP_CONCAT(ts.Specialty, ', ') AS Specialties,
                COUNT(DISTINCT r.MEmail) AS ReservedCount
            FROM GroupSession gs
            JOIN SessionWithBranch swb ON swb.SessionNo = gs.GSessionNo
            JOIN Trains_Group tg ON tg.GSessionNo = gs.GSessionNo
            JOIN StudioHasBranch shb ON shb.StudioNumber = tg.StudioNumber
            JOIN Trainer t ON t.TEmail = tg.TrEmail
            JOIN User u ON u.Email = t.TEmail
            LEFT JOIN Trainer_Specialty ts ON ts.TEmail = t.TEmail
            LEFT JOIN Reserves r ON r.SessionNo = gs.GSessionNo
            WHERE 1=1
        '''
        params = []
        if branch_filter.strip():
            query += ' AND swb.BName = ?'
            params.append(branch_filter.strip())
        if exercise_filter.strip():
            query += ' AND LOWER(gs.ExerciseType) LIKE ?'
            params.append(f'%{exercise_filter.strip().lower()}%')
        if day_filter.strip():
            query += ' AND LOWER(swb.DayOfWeek) = ?'
            params.append(day_filter.strip().lower())
        query += '''
            GROUP BY gs.GSessionNo, gs.ExerciseType, swb.BName, swb.DayOfWeek,
                     swb.StartTime, swb.EndTime, tg.StudioNumber, shb.Capacity,
                     TrainerName, t.TEmail
            ORDER BY swb.StartTime
        '''
        return self.fetchall(query, tuple(params))

    def get_pt_sessions(self, branch_filter='', day_filter=''):
        query = '''
            SELECT
                pt.SessionNo,
                swb.BName,
                swb.DayOfWeek,
                swb.StartTime,
                swb.EndTime,
                u.Name || ' ' || u.Surname AS TrainerName,
                t.TEmail,
                GROUP_CONCAT(ts.Specialty, ', ') AS Specialties,
                t.Hourly_Fee,
                u.Gender AS TrainerGender,
                COUNT(DISTINCT r.MEmail) AS ReservedCount
            FROM PT_Session_Trains pt
            JOIN SessionWithBranch swb ON swb.SessionNo = pt.SessionNo
            JOIN Trainer t ON t.TEmail = pt.TEmail
            JOIN User u ON u.Email = t.TEmail
            LEFT JOIN Trainer_Specialty ts ON ts.TEmail = t.TEmail
            LEFT JOIN Reserves r ON r.SessionNo = pt.SessionNo
            WHERE 1=1
        '''
        params = []
        if branch_filter.strip():
            query += ' AND swb.BName = ?'
            params.append(branch_filter.strip())
        if day_filter.strip():
            query += ' AND LOWER(swb.DayOfWeek) = ?'
            params.append(day_filter.strip().lower())
        query += '''
            GROUP BY pt.SessionNo, swb.BName, swb.DayOfWeek, swb.StartTime, swb.EndTime,
                     TrainerName, t.TEmail, t.Hourly_Fee, u.Gender
            ORDER BY swb.StartTime
        '''
        return self.fetchall(query, tuple(params))

    def format_session_table(self, rows):
        data = []
        for r in rows:
            data.append([
                r['SessionNo'], r['ExerciseType'], r['BName'], r['DayOfWeek'],
                r['StartTime'], r['EndTime'], r['TrainerName'], r['StudioNumber'],
                f"{r['ReservedCount']}/{r['Capacity']}"
            ])
        return data

    def format_pt_session_table(self, rows):
        data = []
        for r in rows:
            status = 'BOOKED' if r['ReservedCount'] > 0 else 'AVAILABLE'
            data.append([
                r['SessionNo'], r['BName'], r['DayOfWeek'],
                r['StartTime'], r['EndTime'], r['TrainerName'],
                r['Hourly_Fee'], status
            ])
        return data

    def get_group_session_details(self, session_no):
        return self.fetchone(
            '''
            SELECT
                gs.GSessionNo AS SessionNo,
                gs.ExerciseType,
                swb.BName,
                swb.DayOfWeek,
                swb.StartTime,
                swb.EndTime,
                tg.StudioNumber,
                shb.Capacity,
                u.Name || ' ' || u.Surname AS TrainerName,
                t.TEmail,
                GROUP_CONCAT(ts.Specialty, ', ') AS Specialties,
                t.Hourly_Fee,
                COUNT(DISTINCT r.MEmail) AS ReservedCount
            FROM GroupSession gs
            JOIN SessionWithBranch swb ON swb.SessionNo = gs.GSessionNo
            JOIN Trains_Group tg ON tg.GSessionNo = gs.GSessionNo
            JOIN StudioHasBranch shb ON shb.StudioNumber = tg.StudioNumber
            JOIN Trainer t ON t.TEmail = tg.TrEmail
            JOIN User u ON u.Email = t.TEmail
            LEFT JOIN Trainer_Specialty ts ON ts.TEmail = t.TEmail
            LEFT JOIN Reserves r ON r.SessionNo = gs.GSessionNo
            WHERE gs.GSessionNo = ?
            GROUP BY gs.GSessionNo, gs.ExerciseType, swb.BName, swb.DayOfWeek,
                     swb.StartTime, swb.EndTime, tg.StudioNumber, shb.Capacity,
                     TrainerName, t.TEmail, t.Hourly_Fee
            ''',
            (session_no,)
        )

    def get_pt_session_details(self, session_no):
        return self.fetchone(
            '''
            SELECT
                pt.SessionNo,
                swb.BName,
                swb.DayOfWeek,
                swb.StartTime,
                swb.EndTime,
                u.Name || ' ' || u.Surname AS TrainerName,
                t.TEmail,
                GROUP_CONCAT(ts.Specialty, ', ') AS Specialties,
                t.Hourly_Fee,
                u.Gender AS TrainerGender,
                COUNT(DISTINCT r.MEmail) AS ReservedCount
            FROM PT_Session_Trains pt
            JOIN SessionWithBranch swb ON swb.SessionNo = pt.SessionNo
            JOIN Trainer t ON t.TEmail = pt.TEmail
            JOIN User u ON u.Email = t.TEmail
            LEFT JOIN Trainer_Specialty ts ON ts.TEmail = t.TEmail
            LEFT JOIN Reserves r ON r.SessionNo = pt.SessionNo
            WHERE pt.SessionNo = ?
            GROUP BY pt.SessionNo, swb.BName, swb.DayOfWeek, swb.StartTime, swb.EndTime,
                     TrainerName, t.TEmail, t.Hourly_Fee, u.Gender
            ''',
            (session_no,)
        )

    def member_has_conflict(self, member_email, target_session_no):
        target = self.fetchone(
            'SELECT StartTime, EndTime FROM SessionWithBranch WHERE SessionNo = ?',
            (target_session_no,)
        )
        if not target:
            return True
        target_start = datetime.fromisoformat(target['StartTime'])
        target_end = datetime.fromisoformat(target['EndTime'])

        rows = self.fetchall(
            '''
            SELECT swb.SessionNo, swb.StartTime, swb.EndTime
            FROM Reserves r
            JOIN SessionWithBranch swb ON swb.SessionNo = r.SessionNo
            WHERE r.MEmail = ?
            ''',
            (member_email,)
        )
        for row in rows:
            existing_start = datetime.fromisoformat(row['StartTime'])
            existing_end = datetime.fromisoformat(row['EndTime'])
            if self.times_overlap(target_start, target_end, existing_start, existing_end):
                return True
        return False

    def reserve_group_session(self, member_email, session_no):
        details = self.get_group_session_details(session_no)
        if not details:
            return False, 'Invalid group session.'

        already_reserved = self.fetchone(
            'SELECT 1 FROM Reserves WHERE MEmail = ? AND SessionNo = ?',
            (member_email, session_no)
        )
        if already_reserved:
            return False, 'You have already reserved this session.'

        if details['ReservedCount'] >= details['Capacity']:
            return False, 'Reservation failed: this session is full.'

        if self.member_has_conflict(member_email, session_no):
            return False, 'Reservation failed: this session conflicts with your schedule.'

        self.execute('INSERT INTO Reserves (MEmail, SessionNo) VALUES (?, ?)', (member_email, session_no))
        updated_count = self.fetchone('SELECT COUNT(*) AS Cnt FROM Reserves WHERE SessionNo = ?', (session_no,))['Cnt']
        return True, f'Reservation completed successfully. Updated reservation count: {updated_count}'

    def reserve_pt_session(self, member_email, session_no):
        details = self.get_pt_session_details(session_no)
        if not details:
            return False, 'Invalid PT session.'

        already_reserved = self.fetchone(
            'SELECT 1 FROM Reserves WHERE MEmail = ? AND SessionNo = ?',
            (member_email, session_no)
        )
        if already_reserved:
            return False, 'You have already reserved this PT session.'

        if details['ReservedCount'] >= 1:
            return False, 'Reservation failed: this PT slot is already booked by another member.'

        if self.member_has_conflict(member_email, session_no):
            return False, 'Reservation failed: this PT session conflicts with your schedule.'

        self.execute('INSERT INTO Reserves (MEmail, SessionNo) VALUES (?, ?)', (member_email, session_no))
        return True, 'PT session reserved successfully.'

    # -------------------- cancel reservation (Text 3) --------------------
    def cancel_group_reservation(self, member_email, session_no):
        """Cancel a group session reservation. Updates capacity accordingly."""
        reserved = self.fetchone(
            'SELECT 1 FROM Reserves WHERE MEmail = ? AND SessionNo = ?',
            (member_email, session_no)
        )
        if not reserved:
            return False, 'You do not have a reservation for this session.'

        is_group = self.fetchone('SELECT 1 FROM GroupSession WHERE GSessionNo = ?', (session_no,))
        if not is_group:
            return False, 'This is not a group session. Use PT cancellation instead.'

        rate = self.fetchone(
            'SELECT RNumber FROM Rates WHERE SessionNo = ? AND MEmail = ?',
            (session_no, member_email)
        )
        if rate:
            self.execute('DELETE FROM Rating WHERE RNumber = ?', (rate['RNumber'],))
            self.execute('DELETE FROM Rates WHERE RNumber = ?', (rate['RNumber'],))

        self.execute('DELETE FROM Reserves WHERE MEmail = ? AND SessionNo = ?', (member_email, session_no))
        updated_count = self.fetchone('SELECT COUNT(*) AS Cnt FROM Reserves WHERE SessionNo = ?', (session_no,))['Cnt']
        return True, f'Group reservation cancelled. Updated reservation count: {updated_count}'

    def cancel_pt_reservation(self, member_email, session_no):
        """Cancel a PT session reservation. Informs about refund based on trainer hourly fee."""
        reserved = self.fetchone(
            'SELECT 1 FROM Reserves WHERE MEmail = ? AND SessionNo = ?',
            (member_email, session_no)
        )
        if not reserved:
            return False, 'You do not have a reservation for this PT session.'

        pt = self.fetchone('SELECT TEmail FROM PT_Session_Trains WHERE SessionNo = ?', (session_no,))
        if not pt:
            return False, 'This is not a PT session. Use group cancellation instead.'

        trainer = self.fetchone('SELECT Hourly_Fee FROM Trainer WHERE TEmail = ?', (pt['TEmail'],))
        hourly_fee = trainer['Hourly_Fee'] if trainer else 0

        session = self.fetchone(
            'SELECT StartTime, EndTime FROM SessionWithBranch WHERE SessionNo = ?', (session_no,)
        )
        duration_hours = 1.0
        if session:
            start_dt = datetime.fromisoformat(session['StartTime'])
            end_dt = datetime.fromisoformat(session['EndTime'])
            duration_hours = (end_dt - start_dt).total_seconds() / 3600.0

        refund_amount = hourly_fee * duration_hours

        rate = self.fetchone(
            'SELECT RNumber FROM Rates WHERE SessionNo = ? AND MEmail = ?',
            (session_no, member_email)
        )
        if rate:
            self.execute('DELETE FROM Rating WHERE RNumber = ?', (rate['RNumber'],))
            self.execute('DELETE FROM Rates WHERE RNumber = ?', (rate['RNumber'],))

        self.execute('DELETE FROM Reserves WHERE MEmail = ? AND SessionNo = ?', (member_email, session_no))
        return True, f'PT reservation cancelled. Refund amount: {refund_amount:.2f} TL (based on {hourly_fee}/hr x {duration_hours:.1f} hr).'

    # -------------------- member profile (Text 3) --------------------
    def get_member_profile(self, member_email):
        return self.fetchone(
            '''
            SELECT u.Email, u.Name, u.Surname, u.Gender, m.Age, m.Height, m.Weight
            FROM Member m
            JOIN User u ON u.Email = m.MEmail
            WHERE m.MEmail = ?
            ''',
            (member_email,)
        )

    def update_member_profile(self, member_email, new_age, new_height, new_weight, new_email=None):
        """Update member physical attributes. Email must remain unique."""
        try:
            age = int(new_age)
            height = float(new_height)
            weight = float(new_weight)
        except ValueError:
            return False, 'Age must be an integer. Height and weight must be numeric.'

        if new_email and new_email.strip() != member_email:
            new_email = new_email.strip()
            existing = self.fetchone('SELECT 1 FROM User WHERE Email = ?', (new_email,))
            if existing:
                return False, 'Email already taken by another user. Email must remain unique.'
            self.execute('UPDATE User SET Email = ? WHERE Email = ?', (new_email, member_email))
            self.execute('UPDATE Member SET MEmail = ? WHERE MEmail = ?', (new_email, member_email))
            self.execute('UPDATE Reserves SET MEmail = ? WHERE MEmail = ?', (new_email, member_email))
            self.execute('UPDATE Rates SET MEmail = ? WHERE MEmail = ?', (new_email, member_email))
            member_email = new_email

        self.execute(
            'UPDATE Member SET Age = ?, Height = ?, Weight = ? WHERE MEmail = ?',
            (age, height, weight, member_email)
        )
        return True, 'Profile updated successfully.'

    # -------------------- member scheduled sessions (Text 3) --------------------
    def get_member_scheduled_sessions(self, member_email):
        """Return all group + PT sessions the member has reserved, for cancellation view."""
        return self.fetchall(
            '''
            SELECT
                swb.SessionNo,
                swb.BName,
                swb.DayOfWeek,
                swb.StartTime,
                swb.EndTime,
                CASE
                    WHEN gs.GSessionNo IS NOT NULL THEN 'Group'
                    WHEN pt.SessionNo IS NOT NULL THEN 'PT'
                    ELSE 'Unknown'
                END AS SessionType,
                CASE
                    WHEN gs.GSessionNo IS NOT NULL THEN gs.ExerciseType
                    ELSE 'Personal Training'
                END AS ExerciseType,
                COALESCE(
                    (SELECT u2.Name || ' ' || u2.Surname
                     FROM Trains_Group tg JOIN User u2 ON u2.Email = tg.TrEmail
                     WHERE tg.GSessionNo = swb.SessionNo),
                    (SELECT u2.Name || ' ' || u2.Surname
                     FROM PT_Session_Trains pt2 JOIN User u2 ON u2.Email = pt2.TEmail
                     WHERE pt2.SessionNo = swb.SessionNo)
                ) AS TrainerName
            FROM Reserves r
            JOIN SessionWithBranch swb ON swb.SessionNo = r.SessionNo
            LEFT JOIN GroupSession gs ON gs.GSessionNo = swb.SessionNo
            LEFT JOIN PT_Session_Trains pt ON pt.SessionNo = swb.SessionNo
            WHERE r.MEmail = ?
            ORDER BY swb.StartTime DESC
            ''',
            (member_email,)
        )

    # -------------------- rating workflow --------------------
    def get_member_attended_sessions(self, member_email):
        return self.fetchall(
            '''
            SELECT
                swb.SessionNo,
                swb.BName,
                swb.StartTime,
                swb.EndTime,
                CASE
                    WHEN gs.GSessionNo IS NOT NULL THEN 'Group - ' || gs.ExerciseType
                    ELSE 'PT'
                END AS SessionType,
                COALESCE(
                    (SELECT u.Name || ' ' || u.Surname
                     FROM Trains_Group tg JOIN User u ON u.Email = tg.TrEmail
                     WHERE tg.GSessionNo = swb.SessionNo),
                    (SELECT u.Name || ' ' || u.Surname
                     FROM PT_Session_Trains pt JOIN User u ON u.Email = pt.TEmail
                     WHERE pt.SessionNo = swb.SessionNo)
                ) AS TrainerName,
                (SELECT rt.Score FROM Rates ra JOIN Rating rt ON rt.RNumber = ra.RNumber
                 WHERE ra.SessionNo = swb.SessionNo AND ra.MEmail = ?) AS MyScore,
                (SELECT rt.Comment FROM Rates ra JOIN Rating rt ON rt.RNumber = ra.RNumber
                 WHERE ra.SessionNo = swb.SessionNo AND ra.MEmail = ?) AS MyComment
            FROM Reserves r
            JOIN SessionWithBranch swb ON swb.SessionNo = r.SessionNo
            LEFT JOIN GroupSession gs ON gs.GSessionNo = swb.SessionNo
            WHERE r.MEmail = ?
            ORDER BY swb.StartTime DESC
            ''',
            (member_email, member_email, member_email)
        )

    def rate_session(self, member_email, session_no, score, comment):
        """Submit a rating. Only one rating per session per member (Text 3)."""
        reserved = self.fetchone(
            'SELECT 1 FROM Reserves WHERE MEmail = ? AND SessionNo = ?',
            (member_email, session_no)
        )
        if not reserved:
            return False, 'You can only rate sessions you have reserved.'

        try:
            score = int(score)
            if not (1 <= score <= 5):
                raise ValueError
        except ValueError:
            return False, 'Score must be an integer between 1 and 5.'

        existing = self.fetchone(
            'SELECT ra.RNumber FROM Rates ra WHERE ra.SessionNo = ? AND ra.MEmail = ?',
            (session_no, member_email)
        )
        if existing:
            return False, 'You have already rated this session. Only one rating per session is allowed.'

        row = self.fetchone('SELECT COALESCE(MAX(RNumber), 0) + 1 AS NextR FROM Rating')
        next_r = int(row['NextR'])
        self.execute(
            'INSERT INTO Rating (Time, RNumber, Score, Comment) VALUES (?, ?, ?, ?)',
            (datetime.now().strftime(DB_DATETIME_FMT), next_r, score, comment.strip())
        )
        self.execute(
            'INSERT INTO Rates (RNumber, SessionNo, MEmail) VALUES (?, ?, ?)',
            (next_r, session_no, member_email)
        )
        return True, 'Rating submitted successfully. Thank you!'

    # -------------------- trainer workflow --------------------
    def get_trainer_schedule(self, trainer_email):
        group_sessions = self.fetchall(
            '''
            SELECT gs.GSessionNo AS SessionNo,
                   'Group - ' || gs.ExerciseType AS SessionType,
                   swb.BName,
                   swb.DayOfWeek,
                   swb.StartTime,
                   swb.EndTime,
                   CAST(tg.StudioNumber AS TEXT) AS StudioNumber,
                   shb.Capacity,
                   COUNT(r.MEmail) AS ReservedCount
            FROM Trains_Group tg
            JOIN GroupSession gs ON gs.GSessionNo = tg.GSessionNo
            JOIN SessionWithBranch swb ON swb.SessionNo = gs.GSessionNo
            JOIN StudioHasBranch shb ON shb.StudioNumber = tg.StudioNumber
            LEFT JOIN Reserves r ON r.SessionNo = gs.GSessionNo
            WHERE tg.TrEmail = ?
            GROUP BY gs.GSessionNo, gs.ExerciseType, swb.BName, swb.DayOfWeek,
                     swb.StartTime, swb.EndTime, tg.StudioNumber, shb.Capacity
            ''',
            (trainer_email,)
        )
        pt_sessions = self.fetchall(
            '''
            SELECT pt.SessionNo,
                   'PT' AS SessionType,
                   swb.BName,
                   swb.DayOfWeek,
                   swb.StartTime,
                   swb.EndTime,
                   '-' AS StudioNumber,
                   1 AS Capacity,
                   COUNT(r.MEmail) AS ReservedCount
            FROM PT_Session_Trains pt
            JOIN SessionWithBranch swb ON swb.SessionNo = pt.SessionNo
            LEFT JOIN Reserves r ON r.SessionNo = pt.SessionNo
            WHERE pt.TEmail = ?
            GROUP BY pt.SessionNo, swb.BName, swb.DayOfWeek, swb.StartTime, swb.EndTime
            ''',
            (trainer_email,)
        )
        combined = list(group_sessions) + list(pt_sessions)
        combined.sort(key=lambda r: r['StartTime'])
        return combined

    def format_trainer_schedule_table(self, rows):
        data = []
        for r in rows:
            data.append([
                r['SessionNo'], r['SessionType'], r['BName'], r['DayOfWeek'],
                r['StartTime'], r['EndTime'], r['StudioNumber'],
                f"{r['ReservedCount']}/{r['Capacity']}"
            ])
        return data

    def get_session_members_for_trainer(self, trainer_email, session_no):
        owns_group = self.fetchone(
            'SELECT 1 FROM Trains_Group WHERE TrEmail = ? AND GSessionNo = ?',
            (trainer_email, session_no)
        )
        owns_pt = self.fetchone(
            'SELECT 1 FROM PT_Session_Trains WHERE TEmail = ? AND SessionNo = ?',
            (trainer_email, session_no)
        )
        if not owns_group and not owns_pt:
            return None
        return self.fetchall(
            '''
            SELECT u.Email, u.Name, u.Surname, u.Gender, m.Age, m.Height, m.Weight
            FROM Reserves r
            JOIN Member m ON m.MEmail = r.MEmail
            JOIN User u ON u.Email = m.MEmail
            WHERE r.SessionNo = ?
            ORDER BY u.Name, u.Surname
            ''',
            (session_no,)
        )

    # -------------------- admin: view all group sessions & participants (Text 3) --------------------
    def get_all_group_sessions_admin(self, branch_filter='', exercise_filter=''):
        query = '''
            SELECT
                gs.GSessionNo AS SessionNo,
                gs.ExerciseType,
                swb.BName,
                swb.DayOfWeek,
                swb.StartTime,
                swb.EndTime,
                tg.StudioNumber,
                shb.Capacity,
                u.Name || ' ' || u.Surname AS TrainerName,
                COUNT(r.MEmail) AS ReservedCount
            FROM GroupSession gs
            JOIN SessionWithBranch swb ON swb.SessionNo = gs.GSessionNo
            JOIN Trains_Group tg ON tg.GSessionNo = gs.GSessionNo
            JOIN StudioHasBranch shb ON shb.StudioNumber = tg.StudioNumber
            JOIN Trainer t ON t.TEmail = tg.TrEmail
            JOIN User u ON u.Email = t.TEmail
            LEFT JOIN Reserves r ON r.SessionNo = gs.GSessionNo
            WHERE 1=1
        '''
        params = []
        if branch_filter.strip():
            query += ' AND swb.BName = ?'
            params.append(branch_filter.strip())
        if exercise_filter.strip():
            query += ' AND LOWER(gs.ExerciseType) LIKE ?'
            params.append(f'%{exercise_filter.strip().lower()}%')
        query += '''
            GROUP BY gs.GSessionNo, gs.ExerciseType, swb.BName, swb.DayOfWeek,
                     swb.StartTime, swb.EndTime, tg.StudioNumber, shb.Capacity,
                     TrainerName
            ORDER BY swb.StartTime
        '''
        return self.fetchall(query, tuple(params))

    def get_session_participants(self, session_no):
        return self.fetchall(
            '''
            SELECT u.Email, u.Name, u.Surname, u.Gender, m.Age, m.Height, m.Weight
            FROM Reserves r
            JOIN Member m ON m.MEmail = r.MEmail
            JOIN User u ON u.Email = m.MEmail
            WHERE r.SessionNo = ?
            ORDER BY u.Name, u.Surname
            ''',
            (session_no,)
        )


# ==================== GUI ====================

def pick_datetime(title='Select Date & Time', initial_text=''):
    """
    Opens a native Tkinter modal with a tkcalendar Calendar widget for date
    selection and Spinbox controls for hour/minute.
    Returns a string in 'YYYY-MM-DD HH:MM' format, or None if cancelled.
    """
    import tkinter as tk
    from tkcalendar import Calendar

    now = datetime.now()
    try:
        pre = datetime.strptime(initial_text.strip(), DATETIME_FMT)
    except ValueError:
        pre = now

    result = [None]

    root = tk.Toplevel()
    root.title(title)
    root.resizable(False, False)
    root.grab_set()

    cal = Calendar(
        root,
        selectmode='day',
        year=pre.year, month=pre.month, day=pre.day,
        date_pattern='yyyy-mm-dd',
        font=('Arial', 10),
        headersbackground='#4a90d9', headersforeground='white',
        selectbackground='#4a90d9',
        weekendforeground='#cc0000', othermonthforeground='#aaaaaa',
    )
    cal.pack(padx=10, pady=(10, 4))

    time_frame = tk.Frame(root)
    time_frame.pack(pady=(0, 6))
    tk.Label(time_frame, text='Hour:', font=('Arial', 10)).pack(side='left', padx=(8, 2))
    hour_var = tk.StringVar(value=f'{pre.hour:02d}')
    tk.Spinbox(time_frame, from_=0, to=23, width=4, textvariable=hour_var,
               format='%02.0f', font=('Arial', 11), justify='center').pack(side='left')
    tk.Label(time_frame, text='Minute:', font=('Arial', 10)).pack(side='left', padx=(12, 2))
    min_var = tk.StringVar(value=f'{pre.minute:02d}')
    tk.Spinbox(time_frame, from_=0, to=59, width=4, textvariable=min_var,
               format='%02.0f', font=('Arial', 11), justify='center').pack(side='left')

    def on_confirm():
        try:
            h = int(hour_var.get())
            m = int(min_var.get())
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
            result[0] = f"{cal.get_date()} {h:02d}:{m:02d}"
        except ValueError:
            import tkinter.messagebox as mb
            mb.showerror('Invalid Time', 'Hour must be 0-23 and minute 0-59.')
            return
        root.destroy()

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=(0, 10))
    tk.Button(btn_frame, text='Confirm', width=10, bg='#4a90d9', fg='white',
              font=('Arial', 10, 'bold'), command=on_confirm).pack(side='left', padx=6)
    tk.Button(btn_frame, text='Cancel', width=10,
              font=('Arial', 10), command=root.destroy).pack(side='left', padx=6)

    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f'+{(sw - root.winfo_width()) // 2}+{(sh - root.winfo_height()) // 2}')
    root.wait_window()
    return result[0]


def pick_date(title='Select Date', initial_text=''):
    """
    Opens a native Tkinter modal with a tkcalendar Calendar widget for date-only selection.
    Returns a string in 'YYYY-MM-DD' format, or None if cancelled.
    """
    import tkinter as tk
    from tkcalendar import Calendar

    now = datetime.now()
    try:
        pre = datetime.strptime(initial_text.strip(), '%Y-%m-%d')
    except ValueError:
        pre = now

    result = [None]

    root = tk.Toplevel()
    root.title(title)
    root.resizable(False, False)
    root.grab_set()

    cal = Calendar(
        root,
        selectmode='day',
        year=pre.year, month=pre.month, day=pre.day,
        date_pattern='yyyy-mm-dd',
        font=('Arial', 10),
        headersbackground='#4a90d9', headersforeground='white',
        selectbackground='#4a90d9',
        weekendforeground='#cc0000', othermonthforeground='#aaaaaa',
    )
    cal.pack(padx=10, pady=(10, 6))

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=(0, 10))
    tk.Button(btn_frame, text='Confirm', width=10, bg='#4a90d9', fg='white',
              font=('Arial', 10, 'bold'),
              command=lambda: [result.__setitem__(0, cal.get_date()), root.destroy()]).pack(side='left', padx=6)
    tk.Button(btn_frame, text='Cancel', width=10,
              font=('Arial', 10), command=root.destroy).pack(side='left', padx=6)

    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f'+{(sw - root.winfo_width()) // 2}+{(sh - root.winfo_height()) // 2}')
    root.wait_window()
    return result[0]


def make_login_window():
    layout = [
        [sg.Text('Fitness Center Scheduling Database', font=('Any', 16, 'bold'))],
        [sg.Text('Role', size=(12, 1)), sg.Combo(['admin', 'member', 'trainer'], key='-ROLE-', readonly=True, default_value='admin')],
        [sg.Text('Email', size=(12, 1)), sg.Input(key='-EMAIL-')],
        [sg.Text('Password', size=(12, 1)), sg.Input(key='-PASSWORD-', password_char='*')],
        [sg.Button('Login', bind_return_key=True), sg.Button('Create Member Account'), sg.Button('Exit')],
        [sg.HorizontalSeparator()],
        [sg.Text('', key='-MSG-', size=(70, 2), text_color='blue')]
    ]
    return sg.Window('Fitness Center Login', layout, finalize=True)


def make_signup_window():
    layout = [
        [sg.Text('Create Member Account', font=('Any', 14, 'bold'))],
        [sg.Text('Email', size=(12, 1)), sg.Input(key='email')],
        [sg.Text('Name', size=(12, 1)), sg.Input(key='name')],
        [sg.Text('Surname', size=(12, 1)), sg.Input(key='surname')],
        [sg.Text('Password', size=(12, 1)), sg.Input(key='password', password_char='*')],
        [sg.Text('Gender', size=(12, 1)), sg.Input(key='gender')],
        [sg.Text('Age', size=(12, 1)), sg.Input(key='age')],
        [sg.Text('Height (cm)', size=(12, 1)), sg.Input(key='height')],
        [sg.Text('Weight (kg)', size=(12, 1)), sg.Input(key='weight')],
        [sg.Button('Create'), sg.Button('Close')]
    ]
    return sg.Window('Create Member Account', layout, modal=True)


def show_signup_window(app):
    window = make_signup_window()
    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, 'Close'):
            break
        if event == 'Create':
            ok, msg = app.create_member_account(values)
            sg.popup(msg, title='Signup Result')
            if ok:
                break
    window.close()


# -------------------- Admin --------------------

def make_admin_window(app, email):
    branches = [r['Name'] for r in app.get_branches()]
    all_trainers = app.get_all_trainers()
    trainer_emails = [t['TEmail'] for t in all_trainers]

    group_create_tab = [
        [sg.Text('Branch', size=(15, 1)), sg.Combo(branches, key='-A-BRANCH-', readonly=False, enable_events=True, size=(30, 1))],
        [sg.Text('Exercise Type', size=(15, 1)), sg.Input(key='-A-EXERCISE-'), sg.Button('Load Eligible Trainers')],
        [sg.Text('Start', size=(15, 1)),
         sg.Input(key='-A-START-', size=(18, 1), readonly=True),
         sg.Button('📅 Pick Start', key='-A-PICK-START-'),
         sg.Text('Day of week set automatically', text_color='grey')],
        [sg.Text('End', size=(15, 1)),
         sg.Input(key='-A-END-', size=(18, 1), readonly=True),
         sg.Button('📅 Pick End', key='-A-PICK-END-')],
        [sg.Text('Studio Number', size=(15, 1)), sg.Combo([], key='-A-STUDIO-', size=(30, 1), readonly=False)],
        [sg.Text('Trainer', size=(15, 1)), sg.Combo([], key='-A-TRAINER-', size=(45, 1), readonly=False)],
        [sg.Button('Create Group Session'), sg.Button('Refresh Branch Info')],
        [sg.Text('Studios in selected branch:')],
        [sg.Multiline('', size=(100, 5), key='-A-STUDIOS-', disabled=True)],
        [sg.Text('Eligible trainers:')],
        [sg.Multiline('', size=(100, 5), key='-A-TRAINERS-', disabled=True)],
        [sg.Text('', key='-A-MSG-', size=(90, 2), text_color='blue')],
    ]

    pt_tab = [
        [sg.Text('Branch', size=(15, 1)), sg.Combo(branches, key='-AP-BRANCH-', readonly=False, size=(30, 1))],
        [sg.Text('Trainer', size=(15, 1)), sg.Combo(trainer_emails, key='-AP-TRAINER-', size=(45, 1), readonly=False)],
        [sg.Text('Start', size=(15, 1)),
         sg.Input(key='-AP-START-', size=(18, 1), readonly=True),
         sg.Button('📅 Pick Start', key='-AP-PICK-START-'),
         sg.Text('Day of week set automatically', text_color='grey')],
        [sg.Text('End', size=(15, 1)),
         sg.Input(key='-AP-END-', size=(18, 1), readonly=True),
         sg.Button('📅 Pick End', key='-AP-PICK-END-')],
        [sg.Text('All trainers:', font=('Any', 10, 'bold'))],
        [sg.Multiline('', size=(100, 8), key='-AP-TRAINERS-', disabled=True)],
        [sg.Button('Create PT Session')],
        [sg.Text('', key='-AP-MSG-', size=(90, 2), text_color='blue')],
    ]

    # Admin view all group sessions tab (Text 3)
    view_headings = ['Session ID', 'Exercise', 'Branch', 'Day', 'Start', 'End', 'Studio', 'Trainer', 'Reserved']
    view_sessions_tab = [
        [sg.Text('Branch', size=(10, 1)), sg.Combo([''] + branches, key='-AV-BRANCH-', size=(20, 1), readonly=False),
         sg.Text('Exercise', size=(10, 1)), sg.Input(key='-AV-EXERCISE-', size=(15, 1)),
         sg.Button('Search All Group Sessions')],
        [sg.Table(values=[], headings=view_headings, key='-AV-TABLE-', auto_size_columns=False,
                  col_widths=[8, 12, 14, 10, 18, 18, 8, 18, 10],
                  justification='left', expand_x=True, num_rows=10,
                  enable_events=True, select_mode=sg.TABLE_SELECT_MODE_BROWSE)],
        [sg.Button('View Session Participants')],
        [sg.Text('Participants:')],
        [sg.Multiline('', size=(120, 8), key='-AV-PARTICIPANTS-', disabled=True)],
        [sg.Text('', key='-AV-MSG-', size=(90, 2), text_color='blue')],
    ]

    layout = [
        [sg.Text(f'Logged in as ADMIN: {email}', font=('Any', 12, 'bold'))],
        [sg.TabGroup([[
            sg.Tab('Create Group Session', group_create_tab),
            sg.Tab('Create PT Session', pt_tab),
            sg.Tab('View Group Sessions', view_sessions_tab),
        ]])],
        [sg.Button('Logout')]
    ]
    return sg.Window('Admin Panel', layout, finalize=True)


def handle_admin_window(app, email):
    window = make_admin_window(app, email)

    all_trainers = app.get_all_trainers()
    pt_trainer_lines = [
        f"{t['TEmail']} | {t['Name']} {t['Surname']} | Specialties: {t['Specialties']} | Fee: {t['Hourly_Fee']}/hr"
        for t in all_trainers
    ]
    window['-AP-TRAINERS-'].update('\n'.join(pt_trainer_lines))

    current_admin_group_rows = []

    def refresh_studios(branch_name):
        studios = app.get_studios_for_branch(branch_name)
        if not studios:
            window['-A-STUDIOS-'].update('No studios found for this branch.')
            window['-A-STUDIO-'].update(values=[])
            return
        lines = [f"Studio {s['StudioNumber']} | Capacity: {s['Capacity']}" for s in studios]
        window['-A-STUDIOS-'].update('\n'.join(lines))
        window['-A-STUDIO-'].update(values=[str(s['StudioNumber']) for s in studios])

    def refresh_eligible_trainers(exercise_type):
        trainers = app.get_eligible_trainers(exercise_type)
        if not trainers:
            window['-A-TRAINERS-'].update('No eligible trainers found.')
            window['-A-TRAINER-'].update(values=[])
            return
        lines = [
            f"{t['TEmail']} | {t['Name']} {t['Surname']} | Specialties: {t['Specialties']} | Fee: {t['Hourly_Fee']}/hr"
            for t in trainers
        ]
        window['-A-TRAINERS-'].update('\n'.join(lines))
        window['-A-TRAINER-'].update(values=[t['TEmail'] for t in trainers])

    def search_admin_group_sessions():
        nonlocal current_admin_group_rows
        current_admin_group_rows = app.get_all_group_sessions_admin(
            values['-AV-BRANCH-'] or '', values['-AV-EXERCISE-']
        )
        data = []
        for r in current_admin_group_rows:
            data.append([
                r['SessionNo'], r['ExerciseType'], r['BName'], r['DayOfWeek'],
                r['StartTime'], r['EndTime'], r['StudioNumber'], r['TrainerName'],
                f"{r['ReservedCount']}/{r['Capacity']}"
            ])
        window['-AV-TABLE-'].update(values=data)
        window['-AV-PARTICIPANTS-'].update('')
        window['-AV-MSG-'].update(f'{len(current_admin_group_rows)} group session(s) found.', text_color='blue')

    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, 'Logout'):
            break

        # Group session create tab
        if event == '-A-PICK-START-':
            dt = pick_datetime('Pick Group Session Start', values['-A-START-'])
            if dt:
                window['-A-START-'].update(dt)
        if event == '-A-PICK-END-':
            dt = pick_datetime('Pick Group Session End', values['-A-END-'])
            if dt:
                window['-A-END-'].update(dt)
        if event in ('Refresh Branch Info', '-A-BRANCH-'):
            refresh_studios(values['-A-BRANCH-'])
        if event == 'Load Eligible Trainers':
            refresh_eligible_trainers(values['-A-EXERCISE-'])
        if event == 'Create Group Session':
            ok, msg = app.create_group_session(
                values['-A-BRANCH-'], values['-A-STUDIO-'], values['-A-TRAINER-'],
                values['-A-EXERCISE-'], values['-A-START-'], values['-A-END-']
            )
            window['-A-MSG-'].update(msg, text_color='green' if ok else 'red')
            if ok:
                refresh_studios(values['-A-BRANCH-'])

        # PT session tab
        if event == '-AP-PICK-START-':
            dt = pick_datetime('Pick PT Session Start', values['-AP-START-'])
            if dt:
                window['-AP-START-'].update(dt)
        if event == '-AP-PICK-END-':
            dt = pick_datetime('Pick PT Session End', values['-AP-END-'])
            if dt:
                window['-AP-END-'].update(dt)
        if event == 'Create PT Session':
            ok, msg = app.create_pt_session(
                values['-AP-BRANCH-'], values['-AP-TRAINER-'],
                values['-AP-START-'], values['-AP-END-']
            )
            window['-AP-MSG-'].update(msg, text_color='green' if ok else 'red')

        # View group sessions tab (Text 3)
        if event == 'Search All Group Sessions':
            search_admin_group_sessions()
        if event == 'View Session Participants':
            if not values['-AV-TABLE-']:
                window['-AV-MSG-'].update('Please select a session first.', text_color='red')
                continue
            selected = current_admin_group_rows[values['-AV-TABLE-'][0]]
            participants = app.get_session_participants(selected['SessionNo'])
            if not participants:
                window['-AV-PARTICIPANTS-'].update('No members have reserved this session yet.')
            else:
                text = []
                for p in participants:
                    text.append(
                        f"{p['Name']} {p['Surname']} | {p['Email']} | Gender: {p['Gender']} | "
                        f"Age: {p['Age']} | Height: {p['Height']} cm | Weight: {p['Weight']} kg"
                    )
                window['-AV-PARTICIPANTS-'].update('\n'.join(text))
            window['-AV-MSG-'].update(f'{len(participants)} participant(s) found.', text_color='green')

    window.close()


# -------------------- Member --------------------

def make_member_window(app, email):
    branches = [r['Name'] for r in app.get_branches()]
    group_headings = ['Session ID', 'Exercise', 'Branch', 'Day', 'Start', 'End', 'Trainer', 'Studio', 'Reserved']
    pt_headings = ['Session ID', 'Branch', 'Day', 'Start', 'End', 'Trainer', 'Fee/hr', 'Status']
    rating_headings = ['Session ID', 'Type', 'Branch', 'Start', 'End', 'Trainer', 'My Score', 'My Comment']
    sched_headings = ['Session ID', 'Type', 'Exercise', 'Branch', 'Day', 'Start', 'End', 'Trainer']

    # Profile tab (Text 3)
    profile = app.get_member_profile(email)
    profile_tab = [
        [sg.Text('My Profile', font=('Any', 12, 'bold'))],
        [sg.Text('Email', size=(12, 1)), sg.Input(default_text=profile['Email'] if profile else '', key='-PROF-EMAIL-', size=(40, 1))],
        [sg.Text('Name', size=(12, 1)), sg.Text(f"{profile['Name']} {profile['Surname']}" if profile else '', size=(40, 1))],
        [sg.Text('Gender', size=(12, 1)), sg.Text(profile['Gender'] if profile else '', size=(20, 1))],
        [sg.Text('Age', size=(12, 1)), sg.Input(default_text=str(profile['Age']) if profile else '', key='-PROF-AGE-', size=(10, 1))],
        [sg.Text('Height (cm)', size=(12, 1)), sg.Input(default_text=str(profile['Height']) if profile else '', key='-PROF-HEIGHT-', size=(10, 1))],
        [sg.Text('Weight (kg)', size=(12, 1)), sg.Input(default_text=str(profile['Weight']) if profile else '', key='-PROF-WEIGHT-', size=(10, 1))],
        [sg.Button('Update Profile')],
        [sg.Text('', key='-PROF-MSG-', size=(80, 2), text_color='blue')],
    ]

    group_tab = [
        [sg.Text('Branch', size=(10, 1)), sg.Combo(branches, key='-M-BRANCH-', size=(20, 1), readonly=False),
         sg.Text('Exercise', size=(10, 1)), sg.Input(key='-M-EXERCISE-', size=(15, 1)),
         sg.Text('Day', size=(6, 1)),
         sg.Input(key='-M-DAY-', size=(12, 1), readonly=True),
         sg.Button('📅', key='-M-PICK-DAY-', tooltip='Pick a day'),
         sg.Button('✕', key='-M-CLEAR-DAY-', tooltip='Clear day filter'),
         sg.Button('Search Group Sessions')],
        [sg.Table(values=[], headings=group_headings, key='-M-TABLE-', auto_size_columns=False,
                  col_widths=[8, 12, 14, 10, 18, 18, 18, 8, 10],
                  justification='left', expand_x=True, num_rows=10,
                  enable_events=True, select_mode=sg.TABLE_SELECT_MODE_BROWSE)],
        [sg.Button('View Group Session Details'), sg.Button('Reserve Group Session')],
        [sg.Multiline('', size=(120, 8), key='-M-DETAILS-', disabled=True)],
        [sg.Text('', key='-M-MSG-', size=(100, 2), text_color='blue')],
    ]

    pt_tab = [
        [sg.Text('Branch', size=(10, 1)), sg.Combo(branches, key='-MP-BRANCH-', size=(20, 1), readonly=False),
         sg.Text('Day', size=(6, 1)),
         sg.Input(key='-MP-DAY-', size=(12, 1), readonly=True),
         sg.Button('📅', key='-MP-PICK-DAY-', tooltip='Pick a day'),
         sg.Button('✕', key='-MP-CLEAR-DAY-', tooltip='Clear day filter'),
         sg.Button('Search PT Sessions')],
        [sg.Table(values=[], headings=pt_headings, key='-MP-TABLE-', auto_size_columns=False,
                  col_widths=[8, 14, 10, 18, 18, 18, 8, 10],
                  justification='left', expand_x=True, num_rows=10,
                  enable_events=True, select_mode=sg.TABLE_SELECT_MODE_BROWSE)],
        [sg.Button('View PT Session Details'), sg.Button('Reserve PT Session')],
        [sg.Multiline('', size=(120, 8), key='-MP-DETAILS-', disabled=True)],
        [sg.Text('', key='-MP-MSG-', size=(100, 2), text_color='blue')],
    ]

    # My Schedule tab with cancel (Text 3)
    schedule_tab = [
        [sg.Text('Your scheduled sessions (group & PT). Select one to cancel.', font=('Any', 10, 'bold'))],
        [sg.Button('Refresh My Schedule')],
        [sg.Table(values=[], headings=sched_headings, key='-MS-TABLE-', auto_size_columns=False,
                  col_widths=[8, 8, 14, 14, 10, 18, 18, 18],
                  justification='left', expand_x=True, num_rows=10,
                  enable_events=True, select_mode=sg.TABLE_SELECT_MODE_BROWSE)],
        [sg.Button('Cancel Group Reservation'), sg.Button('Cancel PT Reservation')],
        [sg.Text('', key='-MS-MSG-', size=(100, 2), text_color='blue')],
    ]

    rating_tab = [
        [sg.Text('Your attended sessions. Select one to rate it.', font=('Any', 10, 'bold'))],
        [sg.Button('Refresh My Sessions')],
        [sg.Table(values=[], headings=rating_headings, key='-MR-TABLE-', auto_size_columns=False,
                  col_widths=[8, 16, 14, 18, 18, 18, 9, 30],
                  justification='left', expand_x=True, num_rows=10,
                  enable_events=True, select_mode=sg.TABLE_SELECT_MODE_BROWSE)],
        [sg.Text('Score (1-5)', size=(12, 1)), sg.Input(key='-MR-SCORE-', size=(5, 1)),
         sg.Text('Comment', size=(10, 1)), sg.Input(key='-MR-COMMENT-', size=(50, 1)),
         sg.Button('Submit Rating')],
        [sg.Text('', key='-MR-MSG-', size=(100, 2), text_color='blue')],
    ]

    layout = [
        [sg.Text(f'Logged in as MEMBER: {email}', font=('Any', 12, 'bold'))],
        [sg.TabGroup([[
            sg.Tab('My Profile', profile_tab),
            sg.Tab('Group Sessions', group_tab),
            sg.Tab('PT Sessions', pt_tab),
            sg.Tab('My Schedule', schedule_tab),
            sg.Tab('My Ratings', rating_tab),
        ]])],
        [sg.Button('Logout')]
    ]
    return sg.Window('Member Panel', layout, finalize=True)


def handle_member_window(app, email):
    window = make_member_window(app, email)
    current_group_rows = []
    current_pt_rows = []
    current_rating_rows = []
    current_schedule_rows = []
    current_email = email

    def run_group_search():
        nonlocal current_group_rows
        current_group_rows = app.get_group_sessions(
            values['-M-BRANCH-'] or '', values['-M-EXERCISE-'], values['-M-DAY-']
        )
        window['-M-TABLE-'].update(values=app.format_session_table(current_group_rows))
        window['-M-DETAILS-'].update('')
        window['-M-MSG-'].update(f'{len(current_group_rows)} group session(s) found.', text_color='blue')

    def run_pt_search():
        nonlocal current_pt_rows
        current_pt_rows = app.get_pt_sessions(
            values['-MP-BRANCH-'] or '', values['-MP-DAY-']
        )
        window['-MP-TABLE-'].update(values=app.format_pt_session_table(current_pt_rows))
        window['-MP-DETAILS-'].update('')
        window['-MP-MSG-'].update(f'{len(current_pt_rows)} PT session(s) found.', text_color='blue')

    def refresh_my_sessions():
        nonlocal current_rating_rows
        current_rating_rows = app.get_member_attended_sessions(current_email)
        data = []
        for r in current_rating_rows:
            score = r['MyScore'] if r['MyScore'] is not None else '-'
            comment = r['MyComment'] if r['MyComment'] is not None else ''
            data.append([
                r['SessionNo'], r['SessionType'], r['BName'],
                r['StartTime'], r['EndTime'], r['TrainerName'],
                score, comment
            ])
        window['-MR-TABLE-'].update(values=data)
        window['-MR-MSG-'].update(f'{len(current_rating_rows)} attended session(s) loaded.', text_color='blue')

    def refresh_my_schedule():
        nonlocal current_schedule_rows
        current_schedule_rows = app.get_member_scheduled_sessions(current_email)
        data = []
        for r in current_schedule_rows:
            data.append([
                r['SessionNo'], r['SessionType'], r['ExerciseType'], r['BName'],
                r['DayOfWeek'], r['StartTime'], r['EndTime'], r['TrainerName']
            ])
        window['-MS-TABLE-'].update(values=data)
        window['-MS-MSG-'].update(f'{len(current_schedule_rows)} scheduled session(s).', text_color='blue')

    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, 'Logout'):
            break

        # Profile tab (Text 3)
        if event == 'Update Profile':
            new_email = values['-PROF-EMAIL-'].strip()
            ok, msg = app.update_member_profile(
                current_email,
                values['-PROF-AGE-'],
                values['-PROF-HEIGHT-'],
                values['-PROF-WEIGHT-'],
                new_email
            )
            window['-PROF-MSG-'].update(msg, text_color='green' if ok else 'red')
            if ok and new_email and new_email != current_email:
                current_email = new_email

        # Group sessions tab
        if event == '-M-PICK-DAY-':
            dt = pick_date('Pick Day Filter', values['-M-DAY-'])
            if dt:
                window['-M-DAY-'].update(dt)
        if event == '-M-CLEAR-DAY-':
            window['-M-DAY-'].update('')
        if event == 'Search Group Sessions':
            run_group_search()
        if event == 'View Group Session Details':
            if not values['-M-TABLE-']:
                window['-M-MSG-'].update('Please select a session first.', text_color='red')
                continue
            selected = current_group_rows[values['-M-TABLE-'][0]]
            d = app.get_group_session_details(selected['SessionNo'])
            details_text = (
                f"Session ID: {d['SessionNo']}\n"
                f"Exercise Type: {d['ExerciseType']}\n"
                f"Branch: {d['BName']}\n"
                f"Day: {d['DayOfWeek']}\n"
                f"Start: {d['StartTime']}    End: {d['EndTime']}\n"
                f"Trainer: {d['TrainerName']} ({d['TEmail']})\n"
                f"Trainer Specialties: {d['Specialties']}\n"
                f"Trainer Hourly Fee: {d['Hourly_Fee']}\n"
                f"Studio Number: {d['StudioNumber']}\n"
                f"Studio Capacity: {d['Capacity']}\n"
                f"Current Reservations: {d['ReservedCount']}\n"
                f"Reservation Status: {'AVAILABLE' if d['ReservedCount'] < d['Capacity'] else 'FULL'}"
            )
            window['-M-DETAILS-'].update(details_text)
            window['-M-MSG-'].update('Session details displayed.', text_color='green')
        if event == 'Reserve Group Session':
            if not values['-M-TABLE-']:
                window['-M-MSG-'].update('Please select a session first.', text_color='red')
                continue
            selected = current_group_rows[values['-M-TABLE-'][0]]
            confirm = sg.popup_yes_no(
                f"Reserve group session {selected['SessionNo']} ({selected['ExerciseType']})?",
                title='Confirm Reservation'
            )
            if confirm != 'Yes':
                window['-M-MSG-'].update('Reservation cancelled.', text_color='blue')
                continue
            ok, msg = app.reserve_group_session(current_email, selected['SessionNo'])
            window['-M-MSG-'].update(msg, text_color='green' if ok else 'red')
            if ok:
                run_group_search()

        # PT sessions tab
        if event == '-MP-PICK-DAY-':
            dt = pick_date('Pick Day Filter', values['-MP-DAY-'])
            if dt:
                window['-MP-DAY-'].update(dt)
        if event == '-MP-CLEAR-DAY-':
            window['-MP-DAY-'].update('')
        if event == 'Search PT Sessions':
            run_pt_search()
        if event == 'View PT Session Details':
            if not values['-MP-TABLE-']:
                window['-MP-MSG-'].update('Please select a PT session first.', text_color='red')
                continue
            selected = current_pt_rows[values['-MP-TABLE-'][0]]
            d = app.get_pt_session_details(selected['SessionNo'])
            details_text = (
                f"Session ID: {d['SessionNo']}\n"
                f"Session Type: Personal Training\n"
                f"Branch: {d['BName']}\n"
                f"Day: {d['DayOfWeek']}\n"
                f"Start: {d['StartTime']}    End: {d['EndTime']}\n"
                f"Trainer: {d['TrainerName']} ({d['TEmail']})\n"
                f"Trainer Gender: {d['TrainerGender']}\n"
                f"Trainer Specialties: {d['Specialties']}\n"
                f"Trainer Hourly Fee: {d['Hourly_Fee']}\n"
                f"Booking Status: {'BOOKED' if d['ReservedCount'] > 0 else 'AVAILABLE'}"
            )
            window['-MP-DETAILS-'].update(details_text)
            window['-MP-MSG-'].update('PT session details displayed.', text_color='green')
        if event == 'Reserve PT Session':
            if not values['-MP-TABLE-']:
                window['-MP-MSG-'].update('Please select a PT session first.', text_color='red')
                continue
            selected = current_pt_rows[values['-MP-TABLE-'][0]]
            d = app.get_pt_session_details(selected['SessionNo'])
            fee = d['Hourly_Fee'] if d else '?'
            confirm = sg.popup_yes_no(
                f"Reserve PT session {selected['SessionNo']} with {selected['TrainerName']}?\n"
                f"Trainer's hourly fee: {fee} TL\n"
                f"Do you accept this fee and confirm the reservation?",
                title='Confirm PT Reservation & Fee'
            )
            if confirm != 'Yes':
                window['-MP-MSG-'].update('Reservation cancelled.', text_color='blue')
                continue
            ok, msg = app.reserve_pt_session(current_email, selected['SessionNo'])
            window['-MP-MSG-'].update(msg, text_color='green' if ok else 'red')
            if ok:
                run_pt_search()

        # My Schedule tab (Text 3 - cancel reservations)
        if event == 'Refresh My Schedule':
            refresh_my_schedule()
        if event == 'Cancel Group Reservation':
            if not values['-MS-TABLE-']:
                window['-MS-MSG-'].update('Please select a session first.', text_color='red')
                continue
            selected = current_schedule_rows[values['-MS-TABLE-'][0]]
            if selected['SessionType'] != 'Group':
                window['-MS-MSG-'].update('Selected session is not a group session. Use "Cancel PT Reservation".', text_color='red')
                continue
            confirm = sg.popup_yes_no(
                f"Cancel your reservation for group session {selected['SessionNo']} ({selected['ExerciseType']})?",
                title='Confirm Cancellation'
            )
            if confirm != 'Yes':
                window['-MS-MSG-'].update('Cancellation aborted.', text_color='blue')
                continue
            ok, msg = app.cancel_group_reservation(current_email, selected['SessionNo'])
            window['-MS-MSG-'].update(msg, text_color='green' if ok else 'red')
            if ok:
                refresh_my_schedule()
        if event == 'Cancel PT Reservation':
            if not values['-MS-TABLE-']:
                window['-MS-MSG-'].update('Please select a session first.', text_color='red')
                continue
            selected = current_schedule_rows[values['-MS-TABLE-'][0]]
            if selected['SessionType'] != 'PT':
                window['-MS-MSG-'].update('Selected session is not a PT session. Use "Cancel Group Reservation".', text_color='red')
                continue
            confirm = sg.popup_yes_no(
                f"Cancel your reservation for PT session {selected['SessionNo']}?\n"
                f"You will be informed about the refund amount.",
                title='Confirm PT Cancellation'
            )
            if confirm != 'Yes':
                window['-MS-MSG-'].update('Cancellation aborted.', text_color='blue')
                continue
            ok, msg = app.cancel_pt_reservation(current_email, selected['SessionNo'])
            window['-MS-MSG-'].update(msg, text_color='green' if ok else 'red')
            if ok:
                refresh_my_schedule()

        # Ratings tab
        if event == 'Refresh My Sessions':
            refresh_my_sessions()
        if event == 'Submit Rating':
            if not values['-MR-TABLE-']:
                window['-MR-MSG-'].update('Please select a session to rate first.', text_color='red')
                continue
            selected = current_rating_rows[values['-MR-TABLE-'][0]]
            ok, msg = app.rate_session(
                current_email, selected['SessionNo'],
                values['-MR-SCORE-'], values['-MR-COMMENT-']
            )
            window['-MR-MSG-'].update(msg, text_color='green' if ok else 'red')
            if ok:
                refresh_my_sessions()

    window.close()


# -------------------- Trainer --------------------

def make_trainer_window(app, email):
    branches = [r['Name'] for r in app.get_branches()]
    trainer_info = app.get_trainer_info(email)

    sched_headings = ['Session ID', 'Type', 'Branch', 'Day', 'Start', 'End', 'Studio', 'Reserved']

    # Schedule tab
    schedule_tab = [
        [sg.Button('Refresh Schedule'), sg.Button('View Reserved Members')],
        [sg.Table(values=[], headings=sched_headings, key='-T-TABLE-', auto_size_columns=False,
                  col_widths=[8, 16, 14, 10, 18, 18, 8, 10],
                  justification='left', num_rows=12, expand_x=True,
                  enable_events=True, select_mode=sg.TABLE_SELECT_MODE_BROWSE)],
        [sg.Text('Members who reserved the selected session:')],
        [sg.Multiline('', size=(120, 10), key='-T-MEMBERS-', disabled=True)],
        [sg.Text('', key='-T-MSG-', size=(100, 2), text_color='blue')],
    ]

    # PT Management tab (Text 2)
    pt_manage_tab = [
        [sg.Text('Create New PT Session', font=('Any', 11, 'bold'))],
        [sg.Text('Branch', size=(15, 1)), sg.Combo(branches, key='-TP-BRANCH-', size=(30, 1), readonly=False)],
        [sg.Text('Start', size=(15, 1)),
         sg.Input(key='-TP-START-', size=(18, 1), readonly=True),
         sg.Button('📅 Pick Start', key='-TP-PICK-START-')],
        [sg.Text('End', size=(15, 1)),
         sg.Input(key='-TP-END-', size=(18, 1), readonly=True),
         sg.Button('📅 Pick End', key='-TP-PICK-END-')],
        [sg.Button('Create My PT Session')],
        [sg.HorizontalSeparator()],
        [sg.Text('Modify Selected PT Session', font=('Any', 11, 'bold'))],
        [sg.Text('(Select a PT session in the Schedule tab first)', text_color='grey')],
        [sg.Text('New Branch', size=(15, 1)), sg.Combo(branches, key='-TM-BRANCH-', size=(30, 1), readonly=False)],
        [sg.Text('New Start', size=(15, 1)),
         sg.Input(key='-TM-START-', size=(18, 1), readonly=True),
         sg.Button('📅 Pick Start', key='-TM-PICK-START-')],
        [sg.Text('New End', size=(15, 1)),
         sg.Input(key='-TM-END-', size=(18, 1), readonly=True),
         sg.Button('📅 Pick End', key='-TM-PICK-END-')],
        [sg.Button('Modify PT Session'), sg.Button('Delete PT Session')],
        [sg.Text('', key='-TP-MSG-', size=(100, 2), text_color='blue')],
    ]

    # Profile tab (Text 2)
    profile_tab = [
        [sg.Text('My Trainer Profile', font=('Any', 12, 'bold'))],
        [sg.Text(f"Name: {trainer_info['Name']} {trainer_info['Surname']}" if trainer_info else '')],
        [sg.Text(f"Gender: {trainer_info['Gender']}" if trainer_info else '')],
        [sg.Text('Specialties', size=(12, 1)),
         sg.Input(default_text=trainer_info['Specialties'] if trainer_info else '', key='-TPROF-SPEC-', size=(50, 1))],
        [sg.Text('Hourly Fee', size=(12, 1)),
         sg.Input(default_text=str(trainer_info['Hourly_Fee']) if trainer_info else '', key='-TPROF-FEE-', size=(15, 1))],
        [sg.Button('Update Specialties'), sg.Button('Update Hourly Fee')],
        [sg.Text('', key='-TPROF-MSG-', size=(80, 2), text_color='blue')],
    ]

    layout = [
        [sg.Text(f'Logged in as TRAINER: {email}', font=('Any', 12, 'bold'))],
        [sg.TabGroup([[
            sg.Tab('My Schedule', schedule_tab),
            sg.Tab('Manage PT Sessions', pt_manage_tab),
            sg.Tab('My Profile', profile_tab),
        ]])],
        [sg.Button('Logout')]
    ]
    return sg.Window('Trainer Panel', layout, finalize=True)


def handle_trainer_window(app, email):
    window = make_trainer_window(app, email)
    current_rows = []

    def refresh_schedule():
        nonlocal current_rows
        current_rows = app.get_trainer_schedule(email)
        window['-T-TABLE-'].update(values=app.format_trainer_schedule_table(current_rows))
        window['-T-MEMBERS-'].update('')
        window['-T-MSG-'].update(
            f'{len(current_rows)} session(s) in your schedule.', text_color='blue'
        )

    refresh_schedule()

    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, 'Logout'):
            break

        # Schedule tab
        if event == 'Refresh Schedule':
            refresh_schedule()
        if event == 'View Reserved Members':
            if not values['-T-TABLE-']:
                window['-T-MSG-'].update('Please select a session first.', text_color='red')
                continue
            selected = current_rows[values['-T-TABLE-'][0]]
            members = app.get_session_members_for_trainer(email, selected['SessionNo'])
            if members is None:
                window['-T-MSG-'].update('That session is not assigned to you.', text_color='red')
                continue
            if not members:
                window['-T-MEMBERS-'].update('No members have reserved this session yet.')
                window['-T-MSG-'].update('Reservation list loaded.', text_color='green')
                continue
            text = []
            for m in members:
                text.append(
                    f"{m['Name']} {m['Surname']} | {m['Email']} | Gender: {m['Gender']} | "
                    f"Age: {m['Age']} | Height: {m['Height']} cm | Weight: {m['Weight']} kg"
                )
            window['-T-MEMBERS-'].update('\n'.join(text))
            window['-T-MSG-'].update('Reservation list loaded.', text_color='green')

        # PT Management tab (Text 2)
        if event == '-TP-PICK-START-':
            dt = pick_datetime('Pick PT Session Start', values['-TP-START-'])
            if dt:
                window['-TP-START-'].update(dt)
        if event == '-TP-PICK-END-':
            dt = pick_datetime('Pick PT Session End', values['-TP-END-'])
            if dt:
                window['-TP-END-'].update(dt)
        if event == '-TM-PICK-START-':
            dt = pick_datetime('Pick New PT Session Start', values['-TM-START-'])
            if dt:
                window['-TM-START-'].update(dt)
        if event == '-TM-PICK-END-':
            dt = pick_datetime('Pick New PT Session End', values['-TM-END-'])
            if dt:
                window['-TM-END-'].update(dt)
        if event == 'Create My PT Session':
            ok, msg = app.trainer_create_pt_session(
                email, values['-TP-BRANCH-'], values['-TP-START-'], values['-TP-END-']
            )
            window['-TP-MSG-'].update(msg, text_color='green' if ok else 'red')
            if ok:
                refresh_schedule()

        if event == 'Modify PT Session':
            if not values['-T-TABLE-']:
                window['-TP-MSG-'].update('Please select a PT session from the Schedule tab first.', text_color='red')
                continue
            selected = current_rows[values['-T-TABLE-'][0]]
            if 'PT' not in selected['SessionType']:
                window['-TP-MSG-'].update('Selected session is not a PT session. Only PT sessions can be modified here.', text_color='red')
                continue
            ok, msg = app.trainer_modify_pt_session(
                email, selected['SessionNo'],
                values['-TM-BRANCH-'], values['-TM-START-'], values['-TM-END-']
            )
            window['-TP-MSG-'].update(msg, text_color='green' if ok else 'red')
            if ok:
                refresh_schedule()

        if event == 'Delete PT Session':
            if not values['-T-TABLE-']:
                window['-TP-MSG-'].update('Please select a PT session from the Schedule tab first.', text_color='red')
                continue
            selected = current_rows[values['-T-TABLE-'][0]]
            if 'PT' not in selected['SessionType']:
                window['-TP-MSG-'].update('Selected session is not a PT session. Only PT sessions can be deleted here.', text_color='red')
                continue
            confirm = sg.popup_yes_no(
                f"Delete PT session {selected['SessionNo']}?\nThis action cannot be undone.",
                title='Confirm Deletion'
            )
            if confirm != 'Yes':
                window['-TP-MSG-'].update('Deletion cancelled.', text_color='blue')
                continue
            ok, msg = app.trainer_delete_pt_session(email, selected['SessionNo'])
            window['-TP-MSG-'].update(msg, text_color='green' if ok else 'red')
            if ok:
                refresh_schedule()

        # Profile tab (Text 2)
        if event == 'Update Specialties':
            ok, msg = app.update_trainer_specialties(email, values['-TPROF-SPEC-'])
            window['-TPROF-MSG-'].update(msg, text_color='green' if ok else 'red')
        if event == 'Update Hourly Fee':
            ok, msg = app.update_trainer_hourly_fee(email, values['-TPROF-FEE-'])
            window['-TPROF-MSG-'].update(msg, text_color='green' if ok else 'red')

    window.close()


# ==================== MAIN ====================

def main():
    sg.theme('SystemDefault')
    app = FitnessCenterGUIApp(DB_PATH)
    login_window = make_login_window()

    try:
        while True:
            event, values = login_window.read()
            if event in (sg.WIN_CLOSED, 'Exit'):
                break
            if event == 'Create Member Account':
                show_signup_window(app)
            if event == 'Login':
                role = values['-ROLE-']
                email = values['-EMAIL-'].strip()
                password = values['-PASSWORD-']
                if not email or not password:
                    login_window['-MSG-'].update('Please enter both email and password.', text_color='red')
                    continue
                ok, msg = app.login(email, password, role)
                login_window['-MSG-'].update(msg, text_color='green' if ok else 'red')
                if not ok:
                    continue

                login_window.hide()
                if role == 'admin':
                    handle_admin_window(app, email)
                elif role == 'member':
                    handle_member_window(app, email)
                elif role == 'trainer':
                    handle_trainer_window(app, email)
                login_window.un_hide()
    finally:
        login_window.close()
        app.close()


if __name__ == '__main__':
    main()