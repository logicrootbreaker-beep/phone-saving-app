from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import timedelta
from flask import session
import os


app = Flask(__name__)
app.secret_key = 'your_secret_key'  # change this to something secret
# Make sessions non-permanent: expires on browser close
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)
app.secret_key = os.urandom(24)


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# DB config
config = {
    'user': 'root',
    'password': 'mysql_hacky',
    'host': 'localhost',
    'database': 'my_khata'
}

# User loader for Flask-Login
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM settings WHERE id = %s", (user_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    if result:
        return User(result[0], result[1])
    return None

# Login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = mysql.connector.connect(**config)
        cursor = conn.cursor()
        cursor.execute("SELECT id, password_hash FROM settings WHERE username = %s", (username,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            user_id, password_hash = result
            if check_password_hash(password_hash, password):
                user = User(user_id, username)
                session.permanent = True
                login_user(user)
                return redirect(url_for('index'))
            else:
                return "❌ Wrong password"
        else:
            return "❌ User not found"

    return render_template('login.html')

# Logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Change password 
@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        new_password = request.form['new_password']
        new_hash = generate_password_hash(new_password)

        conn = mysql.connector.connect(**config)
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET password_hash = %s WHERE id = %s", (new_hash, current_user.id))
        conn.commit()
        cursor.close()
        conn.close()

        return "✅ Password updated!"
    return render_template('change_password.html')


# Home page
@app.route('/')
@login_required
def index():
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    # Get savings data
    cursor.execute("SELECT SUM(saving), SUM(expense) FROM savings")
    sums = cursor.fetchone()
    total_saving = sums[0] or 0
    total_expense = sums[1] or 0

    cursor.execute("SELECT initial_amount, goal_amount , extras FROM settings LIMIT 1")
    row = cursor.fetchone()
    initial_amount = row[0] or 0
    goal_amount = row[1] or 0
    extra_amount = row[2] or 0

    current_balance = initial_amount + total_saving - total_expense
    net_saved = total_saving - total_expense
    drawer_money = current_balance + extra_amount
    remaining = goal_amount - current_balance if goal_amount > 0 else 0
    progress_percent = (current_balance / goal_amount * 100) if goal_amount > 0 else 0
    progress_percent = max(0, min(progress_percent, 100))

    # People Ledger summary
    cursor.execute("SELECT id, name FROM persons")
    persons = cursor.fetchall()

    people = []
    for pid, name in persons:
        cursor.execute("""
            SELECT 
                SUM(given) AS total_given,
                SUM(received) AS total_received
            FROM person_transactions
            WHERE person_id = %s
        """, (pid,))
        totals = cursor.fetchone()
        total_given = totals[0] or 0
        total_received = totals[1] or 0

        if total_given > total_received:
            to_give = 0
            to_take = total_given - total_received
        else:
            to_give = total_received - total_given
            to_take = 0

        people.append({
            'id': pid,
            'name': name,
            'to_give': to_give,
            'to_take': to_take
        })


    cursor.close()
    conn.close()

    return render_template(
        'index.html',
        total_balance=current_balance,
        initial_amount=initial_amount,
	drawer_money = drawer_money,
	extra_amount=extra_amount,
        net_saved=net_saved,
        goal_amount=goal_amount,
        remaining=remaining,
        progress_percent=progress_percent,
        people=people
    )




# Delete record
@app.route('/Delete/<int:id>')
@login_required
def Delete(id):
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM persons WHERE id = %s", (id,))
    
    conn.commit()  
    cursor.close()
    conn.close()
    return redirect(url_for('index'))



# Add new record
@app.route('/add', methods=['POST'])
@login_required
def add():
    saving = float(request.form['saving'])
    expense = float(request.form['expense'])
    date_str = request.form['date']
    month = datetime.strptime(date_str, '%Y-%m-%d').strftime('%Y-%m')

    # Parse date
    try:
        entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        entry_date = datetime.today().date()

    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO savings (date, saving, expense, month) VALUES (%s, %s, %s, %s)",
            (date_str, saving, expense, month))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('index'))

# History page
@app.route('/history')
@login_required
def history():
    # Get selected month from query parameter, default to current month
    selected_month = request.args.get('month')
    if not selected_month:
        selected_month = datetime.now().strftime('%Y-%m')

    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    # Fetch records for the selected month
    cursor.execute("""
        SELECT id, date, saving, expense 
        FROM savings 
        WHERE month = %s 
        ORDER BY date DESC
    """, (selected_month,))
    records = cursor.fetchall()

    # Add weekday names
    records_with_days = []
    Total_savings = 0
    Total_expense = 0
    for r in records:
        day_name = r[1].strftime('%A') if r[1] else 'Unknown'
        records_with_days.append((r[0], r[1], day_name, r[2], r[3]))
        Total_savings += r[2]
        Total_expense += r[3]

    # Daily sums for chart for that month
    cursor.execute("""
        SELECT date, SUM(saving) AS total_saving, SUM(expense) AS total_expense 
        FROM savings 
        WHERE DATE_FORMAT(date, '%Y-%m') = %s
        GROUP BY date 
        ORDER BY date ASC
    """, (selected_month,))
    daily_data = cursor.fetchall()

    cursor.close()
    conn.close()

    dates = [row[0].strftime('%Y-%m-%d') for row in daily_data]
    savings = [float(row[1]) for row in daily_data]
    expenses = [float(row[2]) for row in daily_data]

    return render_template(
        'history.html',
        records=records_with_days,
        dates=dates,
        savings=savings,
        expenses=expenses,
        Total_savings = Total_savings,
        Total_expense = Total_expense,
        selected_month=selected_month  # pass to template if needed
    )

# Delete record
@app.route('/delete/<int:id>')
@login_required
def delete(id):
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM savings WHERE id = %s", (id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('history'))


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    if request.method == 'POST':
        new_saving = float(request.form['saving'])
        new_expense = float(request.form['expense'])
        new_date = request.form['date']

        cursor.execute(
            "UPDATE savings SET saving = %s, expense = %s, date = %s WHERE id = %s",
            (new_saving, new_expense, new_date, id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('history'))

    cursor.execute("SELECT date, saving, expense FROM savings WHERE id = %s", (id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row:
        return render_template('edit.html', id=id, date=row[0], saving=row[1], expense=row[2])
    else:
        return "❌ Record not found."


# ✅ Add new person
@app.route('/add_person', methods=['POST'])
@login_required
def add_person():
    name = request.form['name']

    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO persons (name) VALUES (%s)", (name,))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('index'))


# ✅ View person transactions
@app.route('/person/<int:person_id>')
@login_required
def person_detail(person_id):
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM persons WHERE id = %s", (person_id,))
    row = cursor.fetchone()
    if not row:
        return "❌ Person not found"

    name = row[0]

    cursor.execute("""
        SELECT id, date, given, received, note
        FROM person_transactions
        WHERE person_id = %s
        ORDER BY date DESC
    """, (person_id,))
    transactions = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('person.html', name=name, person_id=person_id, transactions=transactions)


# ✅ Add transaction for person
@app.route('/add_transaction/<int:person_id>', methods=['POST'])
@login_required
def add_transaction(person_id):
    given = float(request.form['given'] or 0)
    received = float(request.form['received'] or 0)
    note = request.form['note']
    date_str = request.form['date']
    entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO person_transactions (person_id, date, given, received, note)
        VALUES (%s, %s, %s, %s, %s)
    """, (person_id, entry_date, given, received, note))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('person_detail', person_id=person_id))


# ✅ Delete a single transaction by ID
@app.route('/delete_transaction/<int:transaction_id>/<int:person_id>')
@login_required
def delete_transaction(transaction_id, person_id):
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM person_transactions WHERE id = %s",
        (transaction_id,)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('person_detail', person_id=person_id))



@app.route('/past-months')
@login_required
def past_months():
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    # Get unique months except current month
    cursor.execute("""
        SELECT DISTINCT DATE_FORMAT(date, '%Y-%m') as month 
        FROM savings 
        WHERE DATE_FORMAT(date, '%Y-%m') < DATE_FORMAT(CURDATE(), '%Y-%m')
        ORDER BY month DESC
    """)
    months = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('past_months.html', months=months)


@app.route('/history/<month>')
def month_history(month):
    conn = mysql.connector.connect(**config)
    cur = conn.cursor()
    cur.execute("SELECT * FROM savings WHERE month = %s", (month,))
    rows = cur.fetchall()
    return render_template('month_history.html', rows=rows, month=month)



@app.route('/phone-khata', methods=['GET', 'POST'])
@login_required
def phone_khata():

    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    if request.method == 'POST':

    	date = request.form.get('date')
    	saving = request.form.get('saving', 0)
    	expense = request.form.get('expense', 0)
    	note = request.form.get('note', '')

    	saving = float(saving) if saving else 0
    	expense = float(expense) if expense else 0

    	if date:
        	cursor.execute("""
            	INSERT INTO phone_khata (date, saving, expense, note)
            	VALUES (%s, %s, %s, %s)
        	""", (date, saving, expense, note))
        	conn.commit()

    # Totals
    cursor.execute("SELECT SUM(saving), SUM(expense) FROM phone_khata")
    totals = cursor.fetchone()

    total_saving = float(totals[0] or 0)
    total_expense = float(totals[1] or 0)

    goal = 30000
    progress = total_saving - total_expense
    remaining = goal - progress
    percentage = (progress / goal) * 100 if goal > 0 else 0
    milestone = None

    if progress >= 30000:
        milestone = "🎉 Goal Achieved!"
    elif progress >= 25000:
        milestone = "🔥 25K Milestone Reached!"
    elif progress >= 20000:
        milestone = "💪 20K Milestone Reached!"
    elif progress >= 10000:
    	milestone = "🚀 10K Milestone Reached!"

    badges = []

    if progress >= 1000:
    	badges.append("🥉 First 1,000 Saved")

    if progress >= 10000:
    	badges.append("🥈 10K Club")

    if progress >= 20000:
    	badges.append("🥇 20K Achiever")

    if progress >= 30000:
    	badges.append("💎 Goal Master")



    # Recent 5 entries only
    cursor.execute("SELECT * FROM phone_khata ORDER BY date DESC LIMIT 5")
    recent_records = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'phone_dashboard.html',
        progress=progress,
        goal=goal,
        percentage=percentage,
        remaining=remaining,
        recent_records=recent_records,
	milestone=milestone,
        badges=badges

    )


@app.route('/phone-khata-history')
@login_required
def phone_khata_history():

    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    # All records
    cursor.execute("SELECT * FROM phone_khata ORDER BY date DESC")
    records = cursor.fetchall()

    # Totals
    cursor.execute("SELECT SUM(saving), SUM(expense) FROM phone_khata")
    totals = cursor.fetchone()

    total_saving = float(totals[0] or 0)
    total_expense = float(totals[1] or 0)

    # Graph data
    cursor.execute("""
        SELECT date, SUM(saving), SUM(expense)
        FROM phone_khata
        GROUP BY date
        ORDER BY date ASC
    """)
    graph_data = cursor.fetchall()

    cursor.close()
    conn.close()

    dates = [row[0].strftime('%Y-%m-%d') for row in graph_data]
    savings = [float(row[1] or 0) for row in graph_data]
    expenses = [float(row[2] or 0) for row in graph_data]

    return render_template(
        'phone_history.html',
        records=records,
        dates=dates,
        savings=savings,
        expenses=expenses,
        total_saving=total_saving,
        total_expense=total_expense
    )



@app.route('/delete-phone-entry/<int:id>')
@login_required
def delete_phone_entry(id):
    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM phone_khata WHERE id = %s", (id,))
    conn.commit()

    cursor.close()
    conn.close()

    return redirect(url_for('phone_khata_history'))

@app.route('/edit-phone-entry/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_phone_entry(id):

    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    if request.method == 'POST':
        date = request.form['date']
        saving = request.form['saving']
        expense = request.form['expense']
        note = request.form['note']

        cursor.execute("""
            UPDATE phone_khata
            SET date=%s, saving=%s, expense=%s, note=%s
            WHERE id=%s
        """, (date, saving, expense, note, id))

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('phone_khata_history'))

    cursor.execute("SELECT * FROM phone_khata WHERE id=%s", (id,))
    record = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template('edit_phone_entry.html', record=record)


if __name__ == '__main__':
    app.run(debug=True)
