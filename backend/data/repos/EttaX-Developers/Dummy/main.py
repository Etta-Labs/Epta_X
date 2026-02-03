from flask import Flask, render_template


app=Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def index():
    return render_template('login.html')


@app.route('/hello')
def hello():
    return render_template()
print()
app.run()









