from flask import Flask, render_template, redirect, url_for, flash, abort, request, jsonify
from flask_bootstrap import Bootstrap
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from flask_login import UserMixin, login_user, LoginManager, login_required, current_user, logout_user
from forms import ProductForm, LogInForm, RegisterForm
from functools import wraps
from datetime import datetime
import stripe
import os

app = Flask(__name__)
app.config["SECRET_KEY"] = "SECRET"
Bootstrap(app)

##CONNECT TO DB
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", 'sqlite:///shop.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db =SQLAlchemy(app)

stripe_keys = {
    "secret_key": 'sk_test_51INknoEKSbWPUoetID6Ag6nrLLhAVRlHRAM8T5dCzItewAONsjllSPWwHLwNETywkImW0R3S3t9MwhgqA2w9rK7s0098vFjX1N',
    "publishable_key": 'pk_test_51INknoEKSbWPUoetgEsroOJrSzbqfmaFTUvExwJRbbODfRqPJOA2uQoFV8c9guI5mPWzY4NjyHo9iOBX3w7xjVkq00oE4QBOO0',
}

stripe.api_key = stripe_keys["secret_key"]

login_manager = LoginManager()
login_manager.init_app(app)

##CONFIGURE TABLES


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(250), unique=True, nullable=False)
    description = db.Column(db.String(250), nullable=False)
    price = db.Column(db.Float, nullable=False)
    img_url = db.Column(db.String(250), nullable=False)

    item = relationship("Purchase", back_populates='product')


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    name = db.Column(db.String(1000))

    purchases = relationship("Purchase", back_populates='buyer')


class Purchase(db.Model):
    __tablename__ = "purchases"
    id = db.Column(db.Integer, primary_key=True)
    paid = db.Column(db.Boolean, nullable=False)
    buyer = relationship("User", back_populates='purchases')
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    product = relationship("Product", back_populates='item')
    product_id = db.Column(db.Integer,db.ForeignKey('products.id'))


db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def admin_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.id != 1:
            return abort(403)
        return f(*args, **kwargs)
    return decorated_function


@app.route("/")
def index():
    products = Product.query.all()
    return render_template("index.html", current_user=current_user, products=products)


@app.route('/register', methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():

        if User.query.filter_by(email=form.email.data).first():
            flash("That email already exists. Please log in.")
            return redirect(url_for("login"))

        hash_password = generate_password_hash(
            password=form.password.data,
            method='pbkdf2:sha256',
            salt_length=8
        )
        new_user = User(
            email=form.email.data,
            name=form.name.data,
            password=hash_password
        )
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('index'))
    return render_template("register.html", form=form, current_user=current_user)


@app.route('/login', methods=["GET", "POST"])
def login():
    form = LogInForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        user = User.query.filter_by(email=email).first()

        if not user:
            flash("That email does not exist, please try again.")
            return redirect(url_for("login"))
        elif not check_password_hash(user.password, password):
            flash("Password incorrect, please try again.")
            return redirect(url_for("login"))
        else:
            login_user(user)
            return redirect(url_for("index"))

    return render_template("login.html", form=form, current_user=current_user)


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/create-checkout-session', methods=["POST"])
def create_checkout_session():
    in_cart = db.session.query(Purchase).filter(Purchase.buyer_id == current_user.id, Purchase.paid is not True)
    cart = [p.product_id for p in in_cart]
    products = [product for product in Product.query.all() if product.id in cart]
    line_items = []
    for product in products:
        item = {
            "price_data": {
                'currency': 'usd',
                'product_data': {
                    'name': product.title,
                    'images': [product.img_url],
                },
                'unit_amount': 2000,
            },
            'quantity': 1
        }
        line_items.append(item)
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=url_for('success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('index', _external=True)
        )

        return jsonify({"id": session.id})


@app.route('/add-new-product', methods=["GET", "POST"])
@admin_only
def add_new_product():
    form = ProductForm()
    if form.validate_on_submit():
        new_product = Product(
            title=form.title.data,
            description=form.description.data,
            price=form.price.data,
            img_url=form.img_url.data
        )
        db.session.add(new_product)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('new-product.html', current_user=current_user, form=form)


@app.route('/cart')
def cart():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    in_cart = db.session.query(Purchase).filter(Purchase.buyer_id == current_user.id, Purchase.paid is not True)
    cart = [p.product_id for p in in_cart]
    products = [product for product in Product.query.all() if product.id in cart]
    total_price = 0
    for product in products:
        total_price += product.price
    return render_template('cart.html', current_user=current_user, products=products, total_price=total_price)

@app.route('/add-to-cart')
def add_to_cart():
    product_id = request.args.get('id')
    if current_user.is_authenticated:
        new_item = Purchase(
            paid=False,
            buyer_id=current_user.get_id(),
            product_id=product_id
        )
        db.session.add(new_item)
        db.session.commit()
        return redirect(url_for('index'))
    return redirect(url_for('login'))

@app.route('/success')
def success():
    return render_template('success.html')


if __name__ == "__main__":
    app.run(debug=True)