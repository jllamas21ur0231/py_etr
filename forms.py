from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, IntegerField, SelectField, TextAreaField, FileField
from wtforms.validators import DataRequired, Length, Email, NumberRange

class RegisterForm(FlaskForm):
    fullname = StringField('Full Name', validators=[DataRequired(), Length(min=3)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class ProductForm(FlaskForm):
    name = StringField('Product Name', validators=[DataRequired()])
    description = TextAreaField('Description')
    price = IntegerField('Price', validators=[DataRequired(), NumberRange(min=1)])
    stock = IntegerField('Stock', validators=[DataRequired(), NumberRange(min=0)])
    category_id = SelectField('Category', coerce=int, validators=[DataRequired()])
    image = FileField('Product Image')
    submit = SubmitField('Save')

class CategoryForm(FlaskForm):
    name = StringField('Category Name', validators=[DataRequired()])
    submit = SubmitField('Add Category')

class PaymentProofForm(FlaskForm):
    proof = FileField('Upload Proof of Payment', validators=[DataRequired()])
    submit = SubmitField('Upload')