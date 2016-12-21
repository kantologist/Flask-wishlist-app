from flask import Flask, request, make_response, redirect, url_for, \
                    render_template, session, flash, current_app
from . import main
from .forms import EditProfileForm, EditProfileAdminForm, WishForm
from .. import db
from ..models import User, Permission, Role, Product, WishList, Item
from ..email import send_mail
from datetime import datetime
from flask import abort
from flask_login import login_required, current_user
from ..decorators import admin_required, permission_required
from ..utils import allowed_file
from werkzeug.utils import secure_filename
import os
from flask_weasyprint import HTML, render_pdf


@main.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    pagination = Product.query.order_by(Product.timestamp.desc()).paginate(
        page, per_page=current_app.config['FLASKY_POST_PER_PAGE'],
        error_out=False)
    products = pagination.items
    if current_user.is_authenticated:
        wishlists = current_user.wishlists.all()
        if wishlists == []:
            wishlist = WishList(name='default')
            current_user.wishlists.append(wishlist)
            db.session.add(current_user)
            db.session.commit()
        wishlists = current_user.wishlists.all()
        wished=[]
        for wishlist in wishlists:
            for item in wishlist.items.all():
                 wished.append(item.item)
    else:
        wished=[]
        wishlists=[]
    return render_template('index.html',
                           products = products,
                           pagination=pagination,
                           wished=wished,
                           wishlists=wishlists)

@main.route('/upload-products', methods=['GET', 'POST'])
def upload_products():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            app = current_app._get_current_object()
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            return redirect(url_for('.populate',
                                    filename=filename))
    return render_template('upload.html')


@main.route('/company-profile.pdf')
def company_profile():
    html = render_template('wise.html')
    return render_pdf(HTML(string=html))


@main.route('/populate/<filename>')
def populate(filename):
    Product.populate_from_file(filename)
    return redirect(url_for('.index'))

@main.route('/<product_id>/<wishlist>/add-to-wishlist')
def add_to_wishlist(product_id, wishlist):
    product = Product.query.get_or_404(product_id)
    item = Item(product_id=product.id)
    wishlist = WishList.query.filter_by(owner_id=current_user.id,
                                         name=wishlist).first()
    wishlist.items.append(item)
    db.session.add(wishlist)
    db.session.commit()
    return redirect(url_for('.index'))

@main.route('/add-wishlist', methods=['GET', 'POST'])
@login_required
def add_wishlist():
    form = WishForm()
    if form.validate_on_submit():
        name = form.name.data
        wishlist = WishList(name=name,
                            owner_id=current_user.id)
        db.session.add(wishlist)
        db.session.commit()
        return redirect(url_for('.index'))
    return render_template('new_wishlist.html', form=form)

@main.route('/<wishlist>/remove-wishlist')
def remove_wishlist(wishlist):
    wishlist = WishList.query.filter_by(owner_id=current_user.id,
                                         name=wishlist).first()
    db.session.delete(wishlist)
    db.session.commit()
    return redirect(url_for('.index'))



@main.route('/<username>/<wishlist>')
def wishlist(username, wishlist):
    user = User.query.filter_by(username=username).first()
    if user is None:
        abort(404)
    all_wishlists= user.wishlists.all()
    wishlists = WishList.query.filter_by(owner_id=current_user.id,
                                         name=wishlist).first()

    wished=[]
    for item in wishlists.items.all():
             wished.append(item.item)
    items = wishlists.items.all()
    products=[]
    for item in items:
        products.append(item.item)
    return render_template('wishlist.html',
                           user=user,
                           products=products,
                           wishlists=all_wishlists,
                           wished=wished)

@main.route('/<product_id>/remove-from-wishlist')
def remove_from_wishlist(product_id):
    product = Product.query.get_or_404(product_id)
    item = product.items.first()
    wishlist=item.wish
    if wishlist.name != 'default':
        wishlist.items.remove(item)
        db.session.add(wishlist)
        db.session.commit()
    return redirect(url_for('.index'))



@main.route('/user/<username>')
def user(username):
    user = User.query.filter_by(username=username).first()
    if user is None:
        abort(404)
    if current_user.is_authenticated:
        wishlists = current_user.wishlists.all()
        if wishlists == []:
            wishlist = WishList(name='default')
            current_user.wishlists.append(wishlist)
            db.session.add(current_user)
            db.session.commit()
        wishlists = current_user.wishlists.all()
        wished=[]
        for wishlist in wishlists:
            for item in wishlist.items.all():
                 wished.append(item.item)
    else:
        wishlists=[]
    return render_template('user.html', user=user,
                           wishlists=wishlists,
                           wished=wished)


@main.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.location = form.location.data
        current_user.about_me = form.about_me.data
        db.session.add(current_user)
        flash('Your profile has been updated.')
        return redirect(url_for('.user', username=current_user.username))
    form.name.data = current_user.name
    form.location.data = current_user.location
    form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', form=form)



@main.route('/edit-profile/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_profile_admin(id):
    user = User.query.get_or_404(id)
    form = EditProfileAdminForm(user=user)
    if form.validate_on_submit():
        user.email = form.email.data
        user.username = form.username.data
        user.confirmed = form.confirmed.data
        user.role = Role.query.get(form.role.data)
        user.name = form.name.data
        user.location = form.location.data
        user.about_me = form.about_me.data
        db.session.add(user)
        flash('The profile has been updated.')
        return redirect(url_for('.user', username=user.username))
    form.email.data = user.email
    form.username.data = user.username
    form.confirmed.data = user.confirmed
    form.role.data = user.role_id
    form.name.data = user.name
    form.location.data = user.location
    form.about_me.data = user.about_me
    return render_template('edit_profile.html', form=form, user=user)


@main.route('/product/<int:id>')
def product(id):
    product = Product.query.get_or_404(id)
    if current_user.is_authenticated:
        wishlists = current_user.wishlists.all()
        if wishlists == []:
            wishlist = WishList(name='default')
            current_user.wishlists.append(wishlist)
            db.session.add(current_user)
            db.session.commit()
        wishlists = current_user.wishlists.all()
        wished=[]
        for wishlist in wishlists:
            for item in wishlist.items.all():
                 wished.append(item.item)
    else:
        wishlists=[]
    return render_template('product.html', products=[product],
                           wishlists=wishlists,
                           wished=wished)
