import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    user_id = session.get("user_id")

    cash = db.execute("SELECT cash FROM users WHERE user_id = :i", i=user_id)[0]["cash"]

    query = db.execute("""
                       SELECT comp_name, symbol, SUM(shares)
                       FROM transactions JOIN companies
                       ON transactions.comp_id = companies.comp_id
                       WHERE transactions.user_id = :i
                       GROUP BY symbol
                       """, i=user_id)

    shares_total = 0
    for row in query:
        price = lookup(row["symbol"])["price"]
        total = price * row["SUM(shares)"]
        row["price"] = usd(price)
        row["total"] = usd(total)
        shares_total += total

    return render_template("index.html", total=usd(shares_total + cash), rows=query, cash=usd(cash))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":

        if not request.form.get("symbol"):
            return apology("Missing symbol", 400)
        if not request.form.get("shares"):
            return apology("Missing shares", 400)
        try:
            if int(request.form.get("shares")) <= 0:
                return apology("Invalid shares", 400)
        except ValueError:
            return apology("Invalid shares", 400)

        user_id = session.get("user_id")
        if not user_id:
            return apology("Logout and login again", 400)

        query = db.execute("SELECT cash FROM users WHERE user_id = :i", i=user_id)
        if len(query) != 1:
            return apology("User do not exist", 400)

        cash = query[0]["cash"]

        quote_data = lookup(request.form.get("symbol").upper())
        if not quote_data:
            return apology("Invalid symbol", 400)

        shares_price = quote_data["price"] * int(request.form.get("shares"))

        query = db.execute("SELECT comp_id FROM companies WHERE symbol = :s", s=quote_data["symbol"])
        if len(query) == 0:
            comp_id = db.execute("INSERT INTO 'companies' ('comp_name', 'symbol') VALUES (:n, :s)",
                                 n=quote_data["name"], s=quote_data["symbol"])
        else:
            comp_id = query[0]["comp_id"]

        if shares_price > cash:
            return apology("Can't afford", 400)

        db.execute("""
                   INSERT INTO 'transactions' ('user_id', 'comp_id', 'shares', 'price', 'time')
                   VALUES (:u, :c, :s, :p, datetime('now', 'utc'))
                   """, u=user_id, c=comp_id, s=int(request.form.get("shares")), p=quote_data["price"])

        cash -= shares_price
        db.execute("UPDATE users SET cash=:c WHERE user_id = :i", c=cash, i=user_id)

        flash("Bought")

        return redirect("/")
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    user_id = session["user_id"]

    query = db.execute("""
                       SELECT symbol, shares, shares * price, time
                       FROM transactions JOIN companies
                       ON transactions.comp_id = companies.comp_id
                       WHERE transactions.user_id = :i
                       """, i=user_id)

    for row in query:
        row["total"] = usd(abs(row["shares * price"]))

    return render_template("history.html", rows=query)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    session.clear()

    if request.method == "POST":

        if not request.form.get("username"):
            return apology("must provide username", 403)

        elif not request.form.get("password"):
            return apology("must provide password", 403)

        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        session["user_id"] = rows[0]["user_id"]

        return redirect("/")

    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":

        if not request.form.get("symbol"):
            return apology("Missing symbol", 400)

        quote_data = lookup(request.form.get("symbol").upper())

        if not quote_data:
            return apology("Invalid symbol", 400)

        return render_template("quoted.html", name=quote_data["name"],
                               symbol=quote_data["symbol"], usd=usd(quote_data["price"]))
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        data = request.form

        if not data.get("username"):
            return apology("Missing username", 400)
        if not data.get("password"):
            return apology("Missing password", 400)
        if not data.get("password") == data.get("confirmation"):
            return apology("Passwords don't match", 400)

        row = db.execute("SELECT username FROM users WHERE username = :u",
                         u=data.get("username"))
        if len(row) != 0:
            return apology("Username taken", 400)

        user_id = db.execute("INSERT INTO users ('username', 'hash') VALUES (:u, :h)",
                             u=data.get("username"), h=generate_password_hash(data.get("password")))

        session["user_id"] = user_id

        flash('Registered')
        return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    user_id = session.get("user_id")

    if request.method == "POST":
        data = request.form

        if not data.get("symbol"):
            return apology("Missing symbol", 400)
        if not data.get("shares"):
            return apology("Missing shares", 400)

        query = db.execute("""
                           SELECT symbol, SUM(shares), companies.comp_id
                           FROM transactions JOIN companies
                           ON transactions.comp_id = companies.comp_id
                           WHERE transactions.user_id = :i AND symbol = :s
                           GROUP BY symbol
                           """, i=user_id, s=data.get("symbol"))

        if int(data.get("shares")) > query[0]["SUM(shares)"]:
            return apology("Too many shares", 400)

        price = lookup(data.get("symbol"))["price"]

        cash = db.execute("SELECT cash FROM users WHERE user_id = :i", i=user_id)[0]["cash"]

        cash += price * int(data.get("shares"))
        db.execute("UPDATE users SET cash = :c", c=cash)

        db.execute("""
                   INSERT INTO 'transactions' ('user_id', 'comp_id', 'shares', 'price', 'time')
                   VALUES (:u, :c, :s, :p, datetime('now', 'utc'))
                   """, u=user_id, c=query[0]["comp_id"],  p=price,
                   s=-int(request.form.get("shares")))

        flash('Sold')
        return redirect("/")
    else:
        query = db.execute("""
                           SELECT symbol
                           FROM transactions JOIN companies
                           ON transactions.comp_id = companies.comp_id
                           WHERE transactions.user_id = :i
                           GROUP BY symbol
                           """, i=user_id)

        return render_template("sell.html", rows=query)


@app.route("/reset", methods=["GET", "POST"])
@login_required
def reset():
    """Resets user's password"""
    if request.method == "POST":
        data = request.form

        if not data.get("current-password"):
            return apology("Missing current password", 400)
        if not data.get("new-password"):
            return apology("Missing new password", 400)
        if not data.get("new-password") == data.get("new-password-confirm"):
            return apology("Passwords don't match", 400)

        user_id = session["user_id"]

        query = db.execute("SELECT hash FROM users WHERE user_id = :i", i=user_id)

        if not check_password_hash(query[0]["hash"], request.form.get("current-password")):
            return apology("Incorrect password"), 400

        db.execute("UPDATE users SET hash = :h WHERE user_id = :i",
                   h=generate_password_hash(request.form.get("new-password")), i=user_id)

        flash("Password reset")
        return redirect("/")
    else:
        return render_template("reset.html")
