from . import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin, AnonymousUserMixin
from . import login_manager
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from flask import current_app, request
from datetime import datetime
import hashlib
from markdown import markdown
import bleach
from sqlite3 import IntegrityError

class Permission():
    FOLLOW = 0x01
    COMMENT = 0x02
    MODERATE_COMMENTS = 0x08
    ADMINISTER = 0x80

class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    default = db.Column(db.Boolean, default=False, index=True)
    permissions = db.Column(db.Integer)
    users = db.relationship('User', backref='role', lazy='dynamic')

    def __repr__(self):
        return '<Role %r>' % self.name


    @staticmethod
    def insert_roles():
        roles = {
            'User': (Permission.FOLLOW |
                     Permission.COMMENT , True),
            'Moderator':(Permission.COMMENT|
                         Permission.MODERATE_COMMENTS, False),
            'Administrator':(0xff, False)
        }

        for r in roles:
            role = Role.query.filter_by(name=r).first()
            if role is None:
                role = Role(name=r)
            role.permissions = roles[r][0]
            role.default = roles[r][1]
            db.session.add(role)
        db.session.commit()

class WishList(db.Model):
    __tablename__ = 'wishlists'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64))
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    items = db.relationship('Item',
                               backref='wish',
                               lazy = 'dynamic',
                               cascade='all, delete-orphan')

class Item(db.Model):
    __tablename__ = 'items'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    item_id = db.Column(db.Integer, db.ForeignKey('wishlists.id'))



class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(64), unique=True, index=True)
    username = db.Column(db.String(64), unique=True, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))
    password_hash = db.Column(db.String(128))
    confirmed = db.Column(db.Boolean, default=False)
    name = db.Column(db.String(64))
    location = db.Column(db.String(64))
    about_me = db.Column(db.Text())
    member_since = db.Column(db.DateTime(), default=datetime.utcnow)
    last_seen = db.Column(db.DateTime(), default=datetime.utcnow)
    avatar_hash = db.Column(db.String(32))
    wishlists = db.relationship('WishList',
                               backref='owner',
                               lazy = 'dynamic',
                               cascade='all, delete-orphan'
                               )

    def __init__(self, **kwargs):
        super(User,self).__init__(**kwargs)
        if self.role is None and self.avatar_hash is None:
            self.avatar_hash =  hashlib.md5(
                self.email.encode('utf-8')).hexdigest()
            if self.email == current_app.config['FLASKY_ADMIN']:
                self.role = Role.query.filter_by(permissions=0xff).first()
            if self.role is None:
                self.role = Role.query.filter_by(default=True).first()


    def ping(self):
        self.last_seen = datetime.utcnow()
        db.session.add(self)

    def can(self, permissions):
        return self.role is not None and\
            (self.role.permissions & permissions) == permissions

    def is_administrator(self):
        return self.can(Permission.ADMINISTER)


    def __repr__(self):
        return '<User %r>' % self.username

    @property
    def password(self):
        raise AttributeError('password is not a readable  attribute')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self,password):
        return check_password_hash(self.password_hash, password)

    def generate_confirmation_token(self, expiration=3600):
        s = Serializer(current_app.config['SECRET_KEY'], expiration)
        return s.dumps({'confirm': self.id})

    def confirm(self, token):
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token)
        except:
            return False
        if data.get('confirm') != self.id:
            return False
        self.confirmed = True
        db.session.add(self)
        return True

    def gravatar(self, size=100, default = 'identicon', rating='g'):
        if request.is_secure:
            url = 'https://secure.gravatar.com/avatar'
        else:
            url = 'http://www.gravatar.com/avatar'
        hash = self.avatar_hash or\
         hashlib.md5(self.email.encode('utf-8')).hexdigest()
        return '{url}/{hash}?s={size}&d={default}&r={rating}'.format(
            url=url, hash=hash, size=size,
            default=default, rating=rating)


    @staticmethod
    def generate_fake(count=100):
        from sqlalchemy.exc import IntegrityError
        from random import seed
        import forgery_py

        seed()
        for i in range(count):
            u = User(email=forgery_py.internet.email_address(),
            password=forgery_py.lorem_ipsum.word(),
                     username=forgery_py.internet.user_name(True),
                     confirmed=True,
                     name=forgery_py.name.full_name(),
                     location =forgery_py.address.city(),
                     about_me=forgery_py.lorem_ipsum.sentence(),
                     member_since=forgery_py.date.date(True))
            db.session.add(u)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, index=True,
                          default=datetime.utcnow)
    items = db.relationship('Item',
                               backref='item',
                               lazy = 'dynamic',
                               cascade='all, delete-orphan')


    def gravatar(self):
        return self.image_url

    def __repr__(self):
        return '<Product %r>' % self.name



    @staticmethod
    def populate_from_file(filepath, jsonpath=None):
        from xlrd import open_workbook
        from collections import OrderedDict
        import simplejson as json

        wb = open_workbook(filepath)
        s = wb.sheet_by_index(0)

        products = []

        for rownum in range(1, s.nrows):
            product = OrderedDict()
            row_values = s.row_values(rownum)
            product["name of product"] = row_values[0]
            product["description"] = row_values[1]
            product["image url"] = row_values[2]



            if Product.query.filter_by(image_url=row_values[2]).first() ==\
                                                        None:
                p = Product(name=row_values[0],
                            description=row_values[1],
                            image_url=row_values[2])
                db.session.add(p)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
            products.append(product)
        j =json.dumps(products)

        if jsonpath != None:
            with open(jsonpath, "w") as f:
                f.write(j)


    @staticmethod
    def generate_fake(count=100):
        from random import seed, randint, choice
        import forgery_py

        shirts=['https://encrypted-tbn0.gstatic.com/images?'
                'q=tbn:ANd9GcSu_vmUgVc4hY911e2q5w7YxC1oujBho'
                'gJdgLCIpUrwBMglSgUl&reload=on']
        shirts.append('https://encrypted-tbn0.gstatic.com/'
                      'images?q=tbn:ANd9GcQeS-GnHV9g7jN6r'
                      'mfMwHHAMJWiotIXbUnEjQhxAuIPvpV9LldNJg')
        shirts.append('https://encrypted-tbn3.gstatic.com/images'
                      '?q=tbn:ANd9GcTP_z5W2I--ROhM8UgfjRMc4bDePv9T'
                      'n_YKLjgxLBaOt97h5XUqFg')
        shirts.append('https://encrypted-tbn1.gstatic.com/image'
                      's?q=tbn:ANd9GcQxO0wv7UrRqaOCC8xvO9wHiDzI1'
                      '-9pX2e9zmOs1MSl2LDCCu2Ksg')
        shirts.append('https://encrypted-tbn2.gstatic.com/images'
                      '?q=tbn:ANd9GcT9hIUiWzOC_677rOL7y4oXz3XJ9r'
                      '1fsJxxzMlYWGLXtKc7gnpp3A')
        shirts.append('https://encrypted-tbn2.gstatic.com/images'
                      '?q=tbn:ANd9GcQxj3fggfrlYNBtaGS0sAONLB2ADZf'
                      'cAmh3aiEnTPFChiqg_J8L')
        shirts.append('https://encrypted-tbn2.gstatic.com/'
                      'images?q=tbn:ANd9GcRtwI1hhG1M-pKc_'
                      '0XyBNDbMyi6eBhprpodSfSyXpB-Fa4HisAK2Q')
        shirts.append('https://encrypted-tbn0.gstatic.com/images'
                      '?q=tbn:ANd9GcRPf0hPH7yP6o-9QsyThXYDGpN9b6i'
                      '_ISTKhlXfIk5DLTtW1q7uNQ')
        shirts.append('https://encrypted-tbn3.gstatic.com/images?q=tbn'
                      ':ANd9GcT6RdupeyZsthKw4ZiYM48ev_35pQocsU6XQ'
                      'B_W5qJqTckPddwL&reload=on')
        shirts.append('https://encrypted-tbn0.gstatic.com/images?'
                      'q=tbn:ANd9GcTRtHCML-AjEaEe2gPTdDbdCZ2by1l'
                      '4SOejeVWD4Bt-va9sy0Xp')

        seed()
        for i in range(count):
            p = Product(name= forgery_py.name.industry(),
                        description=\
                        forgery_py.lorem_ipsum.sentence(),
                        image_url=choice(shirts),
                     timestamp=forgery_py.date.date(True))
            db.session.add(p)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()



class AnonymousUser(AnonymousUserMixin):

    def can(self, permissions):
        return False

    def is_administrator(self):
        return False


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
login_manager.anonymous_user = AnonymousUser
