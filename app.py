from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
import heapq
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///expenses.db'
db = SQLAlchemy(app)
app.config['SECRET_KEY'] = 'dev-secret-key-change-later'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- DATABASE MODELS ---

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))

class GroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'))
    paid_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200))

class ExpenseSplit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    share_amount = db.Column(db.Float, nullable=False)

# --- ROUTES ---

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/dashboard')
@login_required
def dashboard():
    memberships = GroupMember.query.filter_by(user_id=current_user.id).all()
    groups = [Group.query.get(m.group_id) for m in memberships]
    return render_template('dashboard.html', groups=groups)
from flask import request, redirect, url_for

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        new_user = User(username=username, email=email, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for('dashboard'))

    return render_template('signup.html')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            return "Invalid email or password"

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))
@app.route('/create-group', methods=['GET', 'POST'])
@login_required
def create_group():
    if request.method == 'POST':
        group_name = request.form['group_name']

        new_group = Group(name=group_name, created_by=current_user.id)
        db.session.add(new_group)
        db.session.commit()

        # Automatically add the creator as a member of their own group
        membership = GroupMember(group_id=new_group.id, user_id=current_user.id)
        db.session.add(membership)
        db.session.commit()

        return redirect(url_for('dashboard'))

    return render_template('create_group.html')
def simplify_debts(balances_dict):
    """
    Takes a dict of {user_id: net_balance} and returns a list of
    transactions like [(from_user_id, to_user_id, amount), ...]
    that settles everyone with the minimum number of payments.
    """
    creditors = []  # people who are owed money (positive balance)
    debtors = []    # people who owe money (negative balance)

    for user_id, balance in balances_dict.items():
        if balance > 0.01:
            heapq.heappush(creditors, (-balance, user_id))  # max-heap via negation
        elif balance < -0.01:
            heapq.heappush(debtors, (balance, user_id))  # min-heap (most negative on top)

    transactions = []

    while creditors and debtors:
        max_credit, creditor_id = heapq.heappop(creditors)
        max_debt, debtor_id = heapq.heappop(debtors)

        max_credit = -max_credit  # convert back to positive
        settle_amount = min(max_credit, -max_debt)

        transactions.append((debtor_id, creditor_id, round(settle_amount, 2)))

        remaining_credit = max_credit - settle_amount
        remaining_debt = -max_debt - settle_amount

        if remaining_credit > 0.01:
            heapq.heappush(creditors, (-remaining_credit, creditor_id))
        if remaining_debt > 0.01:
            heapq.heappush(debtors, (-remaining_debt, debtor_id))

    return transactions
@app.route('/group/<int:group_id>')
@login_required
def view_group(group_id):
    group = Group.query.get_or_404(group_id)
    memberships = GroupMember.query.filter_by(group_id=group_id).all()
    members = [User.query.get(m.user_id) for m in memberships]

    # Calculate net balance for each member
    balances = {}
    for member in members:
        balances[member.id] = 0.0

    expenses = Expense.query.filter_by(group_id=group_id).all()
    for expense in expenses:
        # Whoever paid gets credited the full amount
        balances[expense.paid_by] += expense.amount

        # Everyone with a split for this expense gets debited their share
        splits = ExpenseSplit.query.filter_by(expense_id=expense.id).all()
        for split in splits:
            balances[split.user_id] -= split.share_amount

    # Attach readable names to balances for the template
    balance_list = []
    for member in members:
        balance_list.append({
            'username': member.username,
            'amount': round(balances[member.id], 2)
        })
    # Build a clean {user_id: balance} dict for the algorithm
    balances_dict = {member.id: balances[member.id] for member in members}
    settlements = simplify_debts(balances_dict)

    # Convert user_ids in settlements to usernames for display
    settlement_list = []
    for from_id, to_id, amount in settlements:
        from_user = User.query.get(from_id)
        to_user = User.query.get(to_id)
        settlement_list.append({
            'from': from_user.username,
            'to': to_user.username,
            'amount': amount
        })

    return render_template('group.html', group=group, members=members, balances=balance_list, settlements=settlement_list)

@app.route('/group/<int:group_id>/add-member', methods=['POST'])
@login_required
def add_member(group_id):
    username = request.form['username']
    user = User.query.filter_by(username=username).first()

    if user:
        existing = GroupMember.query.filter_by(group_id=group_id, user_id=user.id).first()
        if not existing:
            new_member = GroupMember(group_id=group_id, user_id=user.id)
            db.session.add(new_member)
            db.session.commit()

    return redirect(url_for('view_group', group_id=group_id))
@app.route('/group/<int:group_id>/add-expense', methods=['GET', 'POST'])
@login_required
def add_expense(group_id):
    group = Group.query.get_or_404(group_id)
    memberships = GroupMember.query.filter_by(group_id=group_id).all()
    members = [User.query.get(m.user_id) for m in memberships]

    if request.method == 'POST':
        description = request.form['description']
        amount = float(request.form['amount'])
        paid_by = int(request.form['paid_by'])

        new_expense = Expense(
            group_id=group_id,
            paid_by=paid_by,
            amount=amount,
            description=description
        )
        db.session.add(new_expense)
        db.session.commit()

        # Split equally among all members
        share = amount / len(members)
        for member in members:
            split = ExpenseSplit(
                expense_id=new_expense.id,
                user_id=member.id,
                share_amount=share
            )
            db.session.add(split)
        db.session.commit()

        return redirect(url_for('view_group', group_id=group_id))

    return render_template('add_expense.html', group=group, members=members)
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5001)
