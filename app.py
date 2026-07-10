from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('home.html')
@app.route('/dashboard')
def dashboard():
    groups = ["Goa Trip", "Room 204"]
    return render_template('dashboard.html', groups=groups)

if __name__ == '__main__':
    app.run(debug=True)