from flask import Flask, render_template, redirect, url_for, flash, request, session, send_from_directory
from flask_mysqldb import MySQL
from forms import RegisterForm, LoginForm, ProductForm, CategoryForm, PaymentProofForm
from config import Config
import os
from datetime import datetime

app = Flask(__name__)
app.config.from_object(Config)

mysql = MySQL(app)

# Folder for payment proofs
UPLOAD_FOLDER = 'static/uploads/proofs'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PRODUCT_UPLOAD_FOLDER = 'static/uploads/products'
app.config['PRODUCT_UPLOAD_FOLDER'] = PRODUCT_UPLOAD_FOLDER
os.makedirs(PRODUCT_UPLOAD_FOLDER, exist_ok=True)

# Hardcoded admin for simplicity
ADMIN_EMAIL = 'admin@shop.com'
ADMIN_PASSWORD = 'admin123'

# Helper to check if user is logged in
def login_required(role='customer'):
    def decorator(f):
        def wrapper(*args, **kwargs):
            if 'logged_in' not in session or session.get('role') != role:
                flash('Please log in first', 'warning')
                return redirect(url_for('customer_login' if role == 'customer' else 'admin_login'))
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator

# ====================== CUSTOMER ROUTES ======================

@app.route('/')
def index():
    return redirect(url_for('catalog'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (form.email.data,))
        if cur.fetchone():
            flash('Email already registered', 'danger')
        else:
            cur.execute("INSERT INTO users (fullname, email, password, status) VALUES (%s, %s, %s, 'active')",
                        (form.fullname.data, form.email.data, form.password.data))
            mysql.connection.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('customer_login'))
        cur.close()
    return render_template('customer/register.html', form=form)

@app.route('/customer/login', methods=['GET', 'POST'])
def customer_login():
    form = LoginForm()
    if form.validate_on_submit():
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s AND password = %s AND status = 'active'",
                    (form.email.data, form.password.data))
        user = cur.fetchone()
        cur.close()
        if user:
            session['logged_in'] = True
            session['role'] = 'customer'
            session['user_id'] = user['id']
            session['username'] = user['fullname']
            flash('Login successful!', 'success')
            return redirect(url_for('catalog'))
        flash('Invalid credentials or account inactive', 'danger')
    return render_template('customer/login.html', form=form)

@app.route('/catalog')
def catalog():
    search = request.args.get('search', '')
    category_id = request.args.get('category', '')
    price_filter = request.args.get('price', '')
    stock_filter = request.args.get('stock', '')
    
    cur = mysql.connection.cursor()
    
    base_query = """
        SELECT p.*, c.name as category_name 
        FROM products p 
        LEFT JOIN categories c ON p.category_id = c.id 
        WHERE p.stock > 0 AND p.status = 'approved'
    """
    
    params = []
    if search:
        base_query += " AND (p.name LIKE %s OR p.description LIKE %s)"
        params.extend([f'%{search}%', f'%{search}%'])
    
    if category_id:
        base_query += " AND p.category_id = %s"
        params.append(category_id)
    
    if price_filter == 'low_high':
        base_query += " ORDER BY p.price ASC"
    elif price_filter == 'high_low':
        base_query += " ORDER BY p.price DESC"
    
    if stock_filter == 'low_high':
        base_query += " ORDER BY p.stock ASC"
    elif stock_filter == 'high_low':
        base_query += " ORDER BY p.stock DESC"
    
    cur.execute(base_query, params)
    products = cur.fetchall()
    
    cur.execute("SELECT * FROM categories")
    categories = cur.fetchall()
    cur.close()
    
    return render_template('customer/catalog.html', products=products, categories=categories)

@app.route('/add_to_cart/<int:product_id>')
@login_required('customer')
def add_to_cart(product_id):
    if 'cart' not in session:
        session['cart'] = {}
    if str(product_id) in session['cart']:
        session['cart'][str(product_id)] += 1
    else:
        session['cart'][str(product_id)] = 1
    session.modified = True
    flash('Added to cart!', 'success')
    return redirect(url_for('catalog'))

@app.route('/buy_now/<int:product_id>')
@login_required('customer')
def buy_now(product_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM products WHERE id = %s AND stock > 0 AND status = 'approved'", (product_id,))
    product = cur.fetchone()
    cur.close()
    
    if not product:
        flash('Product not available', 'danger')
        return redirect(url_for('catalog'))
    
    # Create temporary cart with single item
    session['buy_now_item'] = {'product_id': product_id, 'quantity': 1}
    session.modified = True
    return redirect(url_for('buy_now_checkout'))

@app.route('/buy_now_checkout', methods=['GET', 'POST'])
@login_required('customer')
def buy_now_checkout():
    if 'buy_now_item' not in session:
        flash('No item selected for purchase', 'warning')
        return redirect(url_for('catalog'))
    
    product_id = session['buy_now_item']['product_id']
    quantity = session['buy_now_item']['quantity']
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cur.fetchone()
    
    if not product:
        flash('Product not found', 'danger')
        session.pop('buy_now_item', None)
        return redirect(url_for('catalog'))
    
    total = product['price'] * quantity
    
    if request.method == 'POST':
        payment_method = request.form['payment_method']
        cur.execute("""
            INSERT INTO orders (user_id, total_amount, payment_method, status) 
            VALUES (%s, %s, %s, 'Pending')
        """, (session['user_id'], total, payment_method))
        order_id = cur.lastrowid
        
        cur.execute("INSERT INTO order_items (order_id, product_id, quantity) VALUES (%s, %s, %s)",
                    (order_id, product_id, quantity))
        cur.execute("UPDATE products SET stock = stock - %s WHERE id = %s", (quantity, product_id))
        
        mysql.connection.commit()
        cur.close()
        session.pop('buy_now_item', None)
        session.modified = True
        
        if payment_method == 'online':
            return redirect(url_for('upload_payment', order_id=order_id))
        flash('Order placed successfully!', 'success')
        return redirect(url_for('customer_orders'))
    
    cur.close()
    return render_template('customer/checkout.html', total=total, product=product, is_buy_now=True)

@app.route('/cart')
@login_required('customer')
def cart():
    cart_items = []
    total = 0
    if 'cart' in session and session['cart']:
        cur = mysql.connection.cursor()
        for pid, qty in session['cart'].items():
            cur.execute("SELECT * FROM products WHERE id = %s", (pid,))
            product = cur.fetchone()
            if product:
                subtotal = product['price'] * qty
                total += subtotal
                cart_items.append({'product': product, 'quantity': qty, 'subtotal': subtotal})
        cur.close()
    return render_template('customer/cart.html', cart_items=cart_items, total=total)

@app.route('/update_cart/<int:product_id>', methods=['POST'])
@login_required('customer')
def update_cart(product_id):
    qty = int(request.form['quantity'])
    if qty <= 0:
        session['cart'].pop(str(product_id), None)
    else:
        session['cart'][str(product_id)] = qty
    session.modified = True
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
@login_required('customer')
def checkout():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty', 'warning')
        return redirect(url_for('catalog'))
    
    total = 0
    cur = mysql.connection.cursor()
    for pid, qty in session['cart'].items():
        cur.execute("SELECT price FROM products WHERE id = %s", (pid,))
        price = cur.fetchone()['price']
        total += price * qty
    
    if request.method == 'POST':
        payment_method = request.form['payment_method']
        cur.execute("""
            INSERT INTO orders (user_id, total_amount, payment_method, status) 
            VALUES (%s, %s, %s, 'Pending')
        """, (session['user_id'], total, payment_method))
        order_id = cur.lastrowid
        
        for pid, qty in session['cart'].items():
            cur.execute("INSERT INTO order_items (order_id, product_id, quantity) VALUES (%s, %s, %s)",
                        (order_id, pid, qty))
            cur.execute("UPDATE products SET stock = stock - %s WHERE id = %s", (qty, pid))
        
        mysql.connection.commit()
        cur.close()
        session.pop('cart', None)
        session.modified = True
        
        if payment_method == 'online':
            return redirect(url_for('upload_payment', order_id=order_id))
        flash('Order placed successfully!', 'success')
        return redirect(url_for('customer_orders'))
    
    return render_template('customer/checkout.html', total=total, is_buy_now=False)

@app.route('/upload_payment/<int:order_id>', methods=['GET', 'POST'])
@login_required('customer')
def upload_payment(order_id):
    form = PaymentProofForm()
    if form.validate_on_submit():
        file = form.proof.data
        filename = f"proof_{order_id}_{file.filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        cur = mysql.connection.cursor()
        cur.execute("UPDATE orders SET proof_image = %s WHERE id = %s", (filename, order_id))
        mysql.connection.commit()
        cur.close()
        flash('Proof uploaded! Awaiting approval.', 'success')
        return redirect(url_for('customer_orders'))
    return render_template('customer/payment_upload.html', form=form, order_id=order_id)

@app.route('/customer/orders')
@login_required('customer')
def customer_orders():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT o.*, oi.product_id, p.name as product_name, p.image 
        FROM orders o 
        JOIN order_items oi ON o.id = oi.order_id 
        JOIN products p ON oi.product_id = p.id 
        WHERE o.user_id = %s
        ORDER BY o.order_date DESC
    """, (session['user_id'],))
    orders = cur.fetchall()
    cur.close()
    return render_template('customer/orders.html', orders=orders)

@app.route('/cancel_order/<int:order_id>')
@login_required('customer')
def cancel_order(order_id):
    cur = mysql.connection.cursor()
    
    # Check if order belongs to user and can be cancelled
    cur.execute("SELECT * FROM orders WHERE id = %s AND user_id = %s", (order_id, session['user_id']))
    order = cur.fetchone()
    
    if not order:
        flash('Order not found', 'danger')
        return redirect(url_for('customer_orders'))
    
    if order['status'] not in ['Pending']:
        flash('Order cannot be cancelled', 'warning')
        return redirect(url_for('customer_orders'))
    
    # Restore product stock
    cur.execute("""
        SELECT oi.product_id, oi.quantity 
        FROM order_items oi 
        WHERE oi.order_id = %s
    """, (order_id,))
    order_items = cur.fetchall()
    
    for item in order_items:
        cur.execute("UPDATE products SET stock = stock + %s WHERE id = %s", 
                   (item['quantity'], item['product_id']))
    
    # Update order status to Cancelled
    cur.execute("UPDATE orders SET status = 'Cancelled' WHERE id = %s", (order_id,))
    mysql.connection.commit()
    cur.close()
    
    flash('Order cancelled successfully', 'success')
    return redirect(url_for('customer_orders'))

# ====================== ADMIN ROUTES ======================

@app.route('/suggest_product', methods=['POST'])
@login_required()
def suggest_product():
    cur = mysql.connection.cursor()
    
    filename = None
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '':
            filename = f"prod_sugg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
            file.save(os.path.join(app.config['PRODUCT_UPLOAD_FOLDER'], filename))
    
    cur.execute("""
        INSERT INTO products 
        (name, description, price, stock, category_id, status, suggested_by, image) 
        VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s)
    """, (
        request.form['name'],
        request.form['description'],
        request.form['price'],
        request.form.get('stock', 0),
        request.form['category_id'],
        session['user_id'],
        filename
    ))
    mysql.connection.commit()
    cur.close()
    flash('Your product suggestion (with image) has been submitted for approval!', 'success')
    return redirect(url_for('my_suggestions'))

@app.route('/admin/approve_product/<int:pid>')
@login_required('admin')
def approve_product(pid):
    cur = mysql.connection.cursor()
    cur.execute("UPDATE products SET status = 'approved', decline_reason = NULL WHERE id = %s", (pid,))
    mysql.connection.commit()
    cur.close()
    flash('Product approved and now visible!', 'success')
    return redirect(url_for('manage_products'))

@app.route('/admin/decline_product/<int:pid>', methods=['POST'])
@login_required('admin')
def decline_product(pid):
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('Please provide a reason for declining.', 'danger')
        return redirect(url_for('manage_products'))
    
    cur = mysql.connection.cursor()
    cur.execute("UPDATE products SET status = 'declined', decline_reason = %s WHERE id = %s", (reason, pid))
    mysql.connection.commit()
    cur.close()
    flash('Product declined with reason.', 'info')
    return redirect(url_for('manage_products'))

@app.route('/my_suggestions')
@login_required()
def my_suggestions():
    cur = mysql.connection.cursor()
    
    # Get user's suggestions
    cur.execute("""
        SELECT p.*, c.name as category_name 
        FROM products p 
        LEFT JOIN categories c ON p.category_id = c.id 
        WHERE p.suggested_by = %s 
        ORDER BY p.id DESC
    """, (session['user_id'],))
    suggestions = cur.fetchall()
    
    # Get all categories for the modal form
    cur.execute("SELECT * FROM categories")
    categories = cur.fetchall()
    
    cur.close()
    return render_template('customer/my_suggestions.html', suggestions=suggestions, categories=categories)

@app.route('/edit_suggestion/<int:pid>', methods=['GET', 'POST'])
@login_required()
def edit_suggestion(pid):
    cur = mysql.connection.cursor()
    
    # Only check ownership — allow edit even if approved
    cur.execute("SELECT * FROM products WHERE id = %s AND suggested_by = %s", (pid, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        flash('Product not found or not yours.', 'danger')
        cur.close()
        return redirect(url_for('my_suggestions'))
    
    if request.method == 'POST':
        filename = product['image']
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                if filename:
                    old_path = os.path.join(app.config['PRODUCT_UPLOAD_FOLDER'], filename)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                filename = f"prod_sugg_edit_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
                file.save(os.path.join(app.config['PRODUCT_UPLOAD_FOLDER'], filename))
        
        # Reset to pending when edited (so admin reviews changes)
        cur.execute("""
            UPDATE products 
            SET name = %s, description = %s, price = %s, stock = %s, category_id = %s, status = 'pending', image = %s
            WHERE id = %s
        """, (
            request.form['name'],
            request.form['description'],
            request.form['price'],
            request.form.get('stock', 0),
            request.form['category_id'],
            filename,
            pid
        ))
        mysql.connection.commit()
        cur.close()
        flash('Your product has been updated and sent back for review!', 'info')
        return redirect(url_for('my_suggestions'))
    
    cur.execute("SELECT * FROM categories")
    categories = cur.fetchall()
    cur.close()
    
    return render_template('customer/edit_suggestion.html', product=product, categories=categories)

@app.route('/delete_suggestion/<int:pid>')
@login_required()
def delete_suggestion(pid):
    cur = mysql.connection.cursor()
    
    # Only check ownership — allow delete even if approved
    cur.execute("SELECT image FROM products WHERE id = %s AND suggested_by = %s", (pid, session['user_id']))
    product = cur.fetchone()
    
    if not product:
        flash('Product not found or not yours.', 'danger')
    else:
        # Delete image if exists
        if product['image']:
            image_path = os.path.join(app.config['PRODUCT_UPLOAD_FOLDER'], product['image'])
            if os.path.exists(image_path):
                os.remove(image_path)
        
        cur.execute("DELETE FROM products WHERE id = %s", (pid,))
        flash('Product deleted successfully.', 'success')
    
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('my_suggestions'))

#===============
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    form = LoginForm()
    if form.validate_on_submit():
        if form.email.data == ADMIN_EMAIL and form.password.data == ADMIN_PASSWORD:
            session['logged_in'] = True
            session['role'] = 'admin'
            flash('Admin login successful', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('Invalid admin credentials', 'danger')
    return render_template('admin/login.html', form=form)

@app.route('/admin/dashboard')
@login_required('admin')
def admin_dashboard():
    year = request.args.get('year', datetime.now().year, type=int)
    cur = mysql.connection.cursor()
    
    # Top stats
    cur.execute("SELECT COUNT(*) as total_users FROM users")
    total_users = cur.fetchone()['total_users']
    
    cur.execute("SELECT COUNT(*) as total_orders FROM orders")
    total_orders = cur.fetchone()['total_orders']
    
    cur.execute("SELECT SUM(total_amount) as total_sales FROM orders WHERE status IN ('Shipped', 'Delivered')")
    total_sales = cur.fetchone()['total_sales'] or 0
    
    cur.execute("SELECT COUNT(*) as total_products FROM products")
    total_products = cur.fetchone()['total_products']
    
    # Users by month
    cur.execute("""
        SELECT MONTH(created_at) as month, COUNT(*) as count 
        FROM users 
        WHERE YEAR(created_at) = %s 
        GROUP BY MONTH(created_at)
    """, (year,))
    users_by_month_raw = cur.fetchall()
    users_by_month = [0] * 12
    for row in users_by_month_raw:
        if row['month'] and row['count']:
            users_by_month[row['month'] - 1] = int(row['count'])
    
    # Sales by month
    cur.execute("""
        SELECT MONTH(order_date) as month, SUM(total_amount) as sales 
        FROM orders 
        WHERE YEAR(order_date) = %s AND status IN ('Shipped', 'Delivered') 
        GROUP BY MONTH(order_date)
    """, (year,))
    sales_by_month_raw = cur.fetchall()
    sales_by_month = [0.0] * 12
    for row in sales_by_month_raw:
        if row['month'] and row['sales'] is not None:
            sales_by_month[row['month'] - 1] = float(row['sales'])
        else:
            sales_by_month[row['month'] - 1] = 0.0
    
    # Orders for table
    cur.execute("""
        SELECT o.*, u.fullname as customer_name, u.id as user_id,
        DATEDIFF(CURDATE(), o.order_date) as days_since
        FROM orders o 
        JOIN users u ON o.user_id = u.id 
        ORDER BY o.order_date DESC
    """)
    orders = cur.fetchall()
    
    cur.close()
    return render_template('admin/dashboard.html', total_users=total_users, total_orders=total_orders, 
                           total_sales=total_sales, total_products=total_products, 
                           users_by_month=users_by_month, sales_by_month=sales_by_month, 
                           year=year, orders=orders)

@app.route('/admin/products', methods=['GET', 'POST'])
@login_required('admin')
def manage_products():
    form = ProductForm()
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM categories")
    categories = cur.fetchall()
    form.category_id.choices = [(c['id'], c['name']) for c in categories]

    if form.validate_on_submit():
        # === HANDLE IMAGE UPLOAD ===
        filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                filename = f"prod_admin_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
                file.save(os.path.join(app.config['PRODUCT_UPLOAD_FOLDER'], filename))

        if request.args.get('id'):
            # EDIT EXISTING PRODUCT
            product_id = request.args.get('id')
            cur.execute("SELECT image FROM products WHERE id = %s", (product_id,))
            old_image = cur.fetchone()['image']
            final_image = filename or old_image

            # Delete old image if replaced
            if filename and old_image:
                old_path = os.path.join(app.config['PRODUCT_UPLOAD_FOLDER'], old_image)
                if os.path.exists(old_path):
                    os.remove(old_path)

            cur.execute("""
                UPDATE products 
                SET name=%s, description=%s, price=%s, stock=%s, category_id=%s, image=%s
                WHERE id=%s
            """, (form.name.data, form.description.data, form.price.data, form.stock.data,
                  form.category_id.data, final_image, product_id))
            flash('Product updated successfully!', 'success')

        else:
            # ADD NEW PRODUCT
            cur.execute("""
                INSERT INTO products 
                (name, description, price, stock, category_id, image, status) 
                VALUES (%s, %s, %s, %s, %s, %s, 'approved')
            """, (form.name.data, form.description.data, form.price.data, form.stock.data,
                  form.category_id.data, filename))
            flash('Product added successfully!', 'success')

        mysql.connection.commit()
        cur.close()
        return redirect(url_for('manage_products'))

    # Load product for editing
    product_id = request.args.get('id')
    if product_id:
        cur.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        if product:
            form.name.data = product['name']
            form.description.data = product['description'] or ''
            form.price.data = product['price']
            form.stock.data = product['stock']
            form.category_id.data = product['category_id']

    # Load all products for table
    cur.execute("""
        SELECT p.*, c.name as category_name, u.fullname as suggested_by_name 
        FROM products p 
        LEFT JOIN categories c ON p.category_id = c.id 
        LEFT JOIN users u ON p.suggested_by = u.id
        ORDER BY p.id DESC
    """)
    products = cur.fetchall()
    cur.close()

    return render_template('admin/manage_products.html', form=form, products=products)

@app.route('/admin/delete_product/<int:pid>')
@login_required('admin')
def delete_product(pid):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM products WHERE id = %s", (pid,))
    mysql.connection.commit()
    cur.close()
    flash('Product deleted', 'success')
    return redirect(url_for('manage_products'))

@app.route('/admin/categories', methods=['GET', 'POST'])
@login_required('admin')
def manage_categories():
    form = CategoryForm()
    if form.validate_on_submit():
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO categories (name) VALUES (%s)", (form.name.data,))
        mysql.connection.commit()
        cur.close()
        flash('Category added', 'success')
        return redirect(url_for('manage_categories'))
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM categories")
    categories = cur.fetchall()
    cur.close()
    return render_template('admin/manage_categories.html', form=form, categories=categories)

@app.route('/admin/orders')
@login_required('admin')
def manage_orders():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT o.*, u.fullname as customer_name 
        FROM orders o 
        JOIN users u ON o.user_id = u.id 
        ORDER BY o.order_date DESC
    """)
    orders = cur.fetchall()
    cur.close()
    return render_template('admin/manage_orders.html', orders=orders)

@app.route('/admin/process_order/<int:order_id>', methods=['POST'])
@login_required('admin')
def process_order(order_id):
    action = request.form['action']
    reason = request.form.get('reason', '')
    status = 'Shipped' if action == 'approve' else 'Declined'
    cur = mysql.connection.cursor()
    cur.execute("UPDATE orders SET status = %s, admin_note = %s WHERE id = %s",
                (status, reason, order_id))
    mysql.connection.commit()
    cur.close()
    flash(f'Order {status.lower()}', 'success')
    return redirect(url_for('manage_orders'))

@app.route('/admin/sales_report')
@login_required('admin')
def sales_report():
    period = request.args.get('period', 'daily')
    cur = mysql.connection.cursor()
    if period == 'daily':
        cur.execute("SELECT DATE(order_date) as date, SUM(total_amount) as sales FROM orders WHERE status IN ('Shipped', 'Delivered') GROUP BY DATE(order_date)")
    elif period == 'weekly':
        cur.execute("SELECT WEEK(order_date) as week, SUM(total_amount) as sales FROM orders WHERE status IN ('Shipped', 'Delivered') GROUP BY WEEK(order_date)")
    else:  # monthly
        cur.execute("SELECT MONTH(order_date) as month, SUM(total_amount) as sales FROM orders WHERE status IN ('Shipped', 'Delivered') GROUP BY MONTH(order_date)")
    report = cur.fetchall()
    cur.close()
    return render_template('admin/sales_report.html', report=report, period=period)

@app.route('/admin/users')
@login_required('admin')
def manage_users():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users")
    users = cur.fetchall()
    cur.close()
    return render_template('admin/manage_users.html', users=users)

@app.route('/admin/toggle_user/<int:user_id>')
@login_required('admin')
def toggle_user(user_id):
    cur = mysql.connection.cursor()
    cur.execute("UPDATE users SET status = IF(status='active', 'inactive', 'active') WHERE id = %s", (user_id,))
    mysql.connection.commit()
    cur.close()
    flash('User status updated', 'success')
    return redirect(url_for('manage_users'))

@app.route('/admin/reset_password/<int:user_id>')
@login_required('admin')
def reset_user_password(user_id):
    cur = mysql.connection.cursor()
    # Check if user exists
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if not user:
        flash('User not found', 'danger')
        cur.close()
        return redirect(url_for('manage_users'))
    
    # Reset password to default
    default_password = 'password123'
    cur.execute("UPDATE users SET password = %s WHERE id = %s", (default_password, user_id))
    mysql.connection.commit()
    cur.close()
    flash(f'Password reset successfully for {user["fullname"]}. New password: {default_password}', 'success')
    return redirect(url_for('manage_users'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out', 'info')
    return redirect(url_for('index'))

#=========================================

if __name__ == '__main__':
    app.run(debug=True)