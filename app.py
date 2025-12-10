from flask import Flask, render_template, request, redirect, url_for, flash, session
import psycopg2
import config
from flask import session
from flask_bcrypt import Bcrypt

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
bcrypt = Bcrypt(app)

def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASS,
            host=config.DB_HOST,
            port=config.DB_PORT
        )
        conn.autocommit = True
        print("\u2705 Connected to the database.")
        return conn
    except Exception as e:
        print("\u274c Failed to connect to the database:", e)
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')

        conn = get_db_connection()
        if not conn:
            flash("Database connection error.", "error")
            return redirect(url_for('register'))
        cur = conn.cursor()
        try:
            cur.execute('INSERT INTO AppUser (Name, Email, Password) VALUES (%s, %s, %s)', (name, email, password))
            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            flash('Email already exists.', 'error')
        finally:
            cur.close()
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        if not conn:
            flash("Database connection error.", "error")
            return redirect(url_for('login'))
        cur = conn.cursor()
        cur.execute('SELECT * FROM AppUser WHERE Email = %s', (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and bcrypt.check_password_hash(user[3], password):  # assuming Password is the 4th column
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/rides')
def list_rides():
    conn = get_db_connection()
    if not conn:
        flash("Database connection error.", "error")
        return render_template('rides.html', rides=[])
    cur = conn.cursor()

    query = """
        SELECT r.RideNum, r.DepartureLocation, r.Destination, r.DepartureTime, r.Notes,
               u.Name AS DriverName, d.CarDetails, d.Price, d.AvailableSeats
        FROM RideRequest r
        JOIN AppUser u ON r.UserId = u.UserId
        JOIN DriverRide d ON r.RideNum = d.RideNum
        WHERE d.AvailableSeats > 0
        ORDER BY r.DepartureTime
    """
    cur.execute(query)
    rides = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('rides.html', rides=rides)

@app.route('/offer', methods=['GET', 'POST'])
def offer_ride():
    if 'user_id' not in session:
        flash('Please log in to offer a ride.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_id = session['user_id']
        departure = request.form['departure']
        destination = request.form['destination']
        departure_time = request.form['departure_time']
        seats = request.form['seats']
        car_details = request.form['car_details']
        price = request.form['price']

        conn = get_db_connection()
        if not conn:
            flash("Database connection error.", "error")
            return redirect(url_for('offer_ride'))
        cur = conn.cursor()

        try:
            cur.execute("""
                INSERT INTO RideRequest (UserId, DepartureLocation, Destination, DepartureTime, IsUser_Driver)
                VALUES (%s, %s, %s, %s, TRUE) RETURNING RideNum
            """, (user_id, departure, destination, departure_time))

            ride_num = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO DriverRide (RideNum, AvailableSeats, CarDetails, Price)
                VALUES (%s, %s, %s, %s)
            """, (ride_num, seats, car_details, price))

            conn.commit()
            flash("Ride offered successfully!", "success")
        except Exception as e:
            flash(f"Error offering ride: {e}", "error")
            conn.rollback()
        finally:
            cur.close()
            conn.close()

        return redirect(url_for('list_rides'))

    return render_template('offer_ride.html')

@app.route('/book_ride/<int:ride_id>', methods=['POST'])
def book_ride(ride_id):
    if 'user_id' not in session:
        flash('Please log in to book a ride.', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    if not conn:
        flash("Database connection error.", "error")
        return redirect(url_for('list_rides'))
    cur = conn.cursor()

    try:
        cur.execute('SELECT * FROM Booking WHERE UserId = %s AND RideNum = %s', (user_id, ride_id))
        if cur.fetchone():
            flash('You already booked this ride.', 'error')
        else:
            cur.execute('INSERT INTO Booking (UserId, RideNum) VALUES (%s, %s)', (user_id, ride_id))
            cur.execute('UPDATE DriverRide SET AvailableSeats = AvailableSeats - 1 WHERE RideNum = %s AND AvailableSeats > 0', (ride_id,))
            conn.commit()
            flash('Ride booked successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f"Error booking ride: {e}", "error")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('list_rides'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash("Please log in to access your dashboard.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    if not conn:
        flash("Database connection error.", "error")
        return redirect(url_for('index'))
    cur = conn.cursor()

    try:
        # Upcoming bookings (as passenger)
        cur.execute("""
            SELECT r.DepartureLocation, r.Destination, r.DepartureTime
            FROM Booking b
            JOIN RideRequest r ON b.RideNum = r.RideNum
            WHERE b.UserId = %s
            ORDER BY r.DepartureTime
        """, (user_id,))
        bookings = cur.fetchall()

        # Rides offered (as driver)
        cur.execute("""
            SELECT r.DepartureLocation, r.Destination, r.DepartureTime, d.AvailableSeats
            FROM RideRequest r
            JOIN DriverRide d ON r.RideNum = d.RideNum
            WHERE r.UserId = %s
            ORDER BY r.DepartureTime
        """, (user_id,))
        offers = cur.fetchall()

    except Exception as e:
        flash(f"Error fetching dashboard info: {e}", "error")
        bookings, offers = [], []
    finally:
        cur.close()
        conn.close()

    return render_template('dashboard.html', bookings=bookings, offers=offers)

@app.route('/dashboard/bookings')
def dashboard_bookings():
    # Check if user is logged in
    if 'user_id' not in session:
        flash("Please log in to access your dashboard.", "error")
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    conn = get_db_connection()
    if not conn:
        flash("Database connection error.", "error")
        return render_template('dashboard.html', bookings=[])
    
    cur = conn.cursor()
    try:
        query = """
            SELECT r.RideNum, r.DepartureLocation, r.Destination, r.DepartureTime,
                   u.UserId, u.Name AS BookerName, u.Email,
                   b.BookingId, b.Status
            FROM RideRequest r
            JOIN Booking b ON r.RideNum = b.RideNum
            JOIN AppUser u ON b.UserId = u.UserId
            WHERE r.UserId = %s
            ORDER BY r.DepartureTime
        """
        cur.execute(query, (user_id,))
        bookings = cur.fetchall()
    except Exception as e:
        flash(f"Error loading bookings: {e}", "error")
        bookings = []
    finally:
        cur.close()
        conn.close()

    return render_template('dashboard.html', bookings=bookings)


@app.route('/my_bookings')
def my_bookings():
    if 'user_id' not in session:
        flash("Please log in to view your bookings.", "error")
        return redirect(url_for('login'))

    driver_id = session['user_id']

    conn = get_db_connection()
    if not conn:
        flash("Database connection error.", "error")
        return render_template('my_bookings.html', bookings=[])
    cur = conn.cursor()

    query = """
    SELECT r.RideNum, r.DepartureLocation, r.Destination, r.DepartureTime,
           u.UserId, u.Name AS BookerName, u.Email
    FROM RideRequest r
    JOIN Booking b ON r.RideNum = b.RideNum
    JOIN AppUser u ON b.UserId = u.UserId
    WHERE r.UserId = %s
    ORDER BY r.DepartureTime
"""

    cur.execute(query, (driver_id,))
    bookings = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('my_bookings.html', bookings=bookings)

@app.route('/confirm_booking/<int:ride_num>/<int:user_id>', methods=['POST'])
def confirm_booking(ride_num, user_id):
    if 'user_id' not in session:
        flash("Please log in first.", "error")
        return redirect(url_for('login'))

    driver_id = session['user_id']

    conn = get_db_connection()
    if not conn:
        flash("Database connection error.", "error")
        return redirect(url_for('my_bookings'))
    cur = conn.cursor()

    try:
        # Check if the ride belongs to this driver
        cur.execute("SELECT UserId FROM RideRequest WHERE RideNum = %s", (ride_num,))
        ride_owner = cur.fetchone()
        if not ride_owner or ride_owner[0] != driver_id:
            flash("Unauthorized action.", "error")
            return redirect(url_for('my_bookings'))

        # Update booking status to confirmed - you need to have a 'Status' column in Booking (add it if missing)
        cur.execute("""
            UPDATE Booking SET Status = 'confirmed' WHERE RideNum = %s AND UserId = %s
        """, (ride_num, user_id))

        conn.commit()
        flash("Booking confirmed.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error confirming booking: {e}", "error")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('my_bookings'))


@app.route('/cancel_booking/<int:ride_num>/<int:user_id>', methods=['POST'])
def cancel_booking(ride_num, user_id):
    if 'user_id' not in session:
        flash("Please log in first.", "error")
        return redirect(url_for('login'))

    conn = get_db_connection()
    if not conn:
        flash("Database connection error.", "error")
        return redirect(url_for('my_bookings'))

    cur = conn.cursor()

    try:
        # Check if booking is not already confirmed
        cur.execute("""
            SELECT Status FROM Booking WHERE RideNum = %s AND UserId = %s
        """, (ride_num, user_id))
        status = cur.fetchone()
        if not status or status[0] == 'confirmed':
            flash("Confirmed bookings cannot be cancelled.", "error")
            return redirect(url_for('my_bookings'))

        # Proceed to cancel
        cur.execute("""
            UPDATE Booking SET Status = 'cancelled' WHERE RideNum = %s AND UserId = %s
        """, (ride_num, user_id))
        conn.commit()
        flash("Booking cancelled.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Error cancelling booking: {e}", "error")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('my_bookings'))



@app.route('/profile')
def profile():
    if 'user_id' not in session:
        flash('Please log in to view your profile.', 'error')
        return redirect(url_for('login'))
    return f"<h2>Welcome, {session['user_name']}!</h2>"

if __name__ == '__main__':
    app.run(debug=True)
