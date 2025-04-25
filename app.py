from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import requests
from flask_mail import Mail, Message
import re
from werkzeug.security import generate_password_hash, check_password_hash
from transformers import pipeline
import os
from dotenv import load_dotenv
import random
from supabase import create_client
from functools import lru_cache
import time

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

# Supabase Configuration
supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)

# NewsAPI Configuration
NEWSAPI_KEY = os.getenv('NEWSAPI_KEY')
NEWSAPI_URL = "https://newsapi.org/v2/top-headlines"

# Initialize summarizer with device='cuda' if available
import torch
device = 'cuda' if torch.cuda.is_available() else 'cpu'
summarizer = pipeline("summarization", model="facebook/bart-large-cnn", device=device)

# Email configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
mail = Mail(app)

# Cache configuration
NEWS_CACHE_TIMEOUT = 300  # 5 minutes cache

@lru_cache(maxsize=10)
def fetch_news_cached(category, timestamp):
    """Cached version of news fetching with timestamp to control cache invalidation"""
    params = {
        "apiKey": NEWSAPI_KEY,
        "category": category,
        "language": "en",
        "country": "us",
        "pageSize": 100  # Maximize articles per request
    }
    try:
        response = requests.get(NEWSAPI_URL, params=params, timeout=5)  # Add timeout
        response.raise_for_status()
        data = response.json()
        articles = data.get("articles", [])
        
        # Filter and process articles more efficiently
        filtered_articles = [
            {k: v for k, v in article.items() if k in ['title', 'description', 'url', 'urlToImage', 'content']}
            for article in articles
            if article.get("content") and len(article["content"]) >= 50
        ]
        return filtered_articles
    except requests.exceptions.RequestException as e:
        app.logger.error(f'Error fetching news: {str(e)}')
        return None

def get_cached_news(category="general"):
    """Get news with cache invalidation control"""
    # Use current timestamp rounded to 5 minutes to control cache
    timestamp = int(time.time() / NEWS_CACHE_TIMEOUT) * NEWS_CACHE_TIMEOUT
    return fetch_news_cached(category, timestamp)

# Routes optimization
@app.route('/')
def index():
    if 'loggedin' in session:
        return render_template('index.html', loggedin=True, name=session['name'])
    return redirect(url_for('login'))

@app.route('/latest-news', methods=["GET"])
def get_latest_news():
    category = request.args.get("category", "general")
    news_data = get_cached_news(category)
    if news_data:
        return jsonify({"articles": news_data})
    return jsonify({"error": "Unable to fetch news"})

@app.route('/categories')
def categories():
    return render_template('categories.html', loggedin='loggedin' in session, name=session.get('name'))

@app.route('/saved')
def saved():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    user_id = session['id']
    response = supabase.table('saved_articles').select('*').eq('user_id', user_id).execute()
    saved_articles = response.data
    return render_template('saved.html', articles=saved_articles)

@app.route('/save_article', methods=['POST'])
def save_article():
    if 'loggedin' not in session:
        return jsonify({'error': 'User not logged in'})
    
    user_id = session['id']
    data = request.json
    
    article_data = {
        'user_id': user_id,
        'title': data.get('title'),
        'url': data.get('url'),
        'image_url': data.get('urlToImage')  # Changed from urlToImage to image_url
    }
    
    response = supabase.table('saved_articles').insert(article_data).execute()
    return jsonify({'success': 'Article saved'})

@app.route('/summarize_article', methods=['POST'])
def summarize_article():
    data = request.json
    article_content = data.get('content')

    if not article_content:
        return jsonify({'error': 'No content provided for summarization'})

    try:
        # Optimize content length for processing
        max_input_length = 1024  # Reduced for better performance
        article_content = article_content[:max_input_length]

        summary = summarizer(
            article_content,
            max_length=100,
            min_length=30,
            do_sample=False,
            num_beams=2,  # Add beam search for better quality
            early_stopping=True
        )
        return jsonify({'summary': summary[0]['summary_text']})
    except Exception as e:
        app.logger.error(f'Summarization error: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        date_of_birth = request.form['date_of_birth']
        otp = str(random.randint(100000, 999999))

        # Check if user exists
        response = supabase.table('users').select('*').eq('email', email).execute()
        if response.data:
            flash('Account already exists!', 'error')
            return render_template('signup.html')
        elif not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            flash('Invalid email address!', 'error')
            return render_template('signup.html')
        elif not name or not password or not email or not date_of_birth:
            flash('Please fill out the form!', 'error')
            return render_template('signup.html')
        else:
            try:
                user_data = {
                    'name': name,
                    'email': email,
                    'password': password,
                    'date_of_birth': date_of_birth,
                    'otp': otp
                }
                response = supabase.table('users').insert(user_data).execute()

                if response.data:
                    # Send OTP to the user's email
                    msg = Message('Your OTP for Registration', sender='noreply@demo.com', recipients=[email])
                    msg.body = f'Your OTP is {otp}'
                    mail.send(msg)

                    session['email'] = email
                    flash('OTP has been sent to your email. Please verify.', 'success')
                    return redirect(url_for('verify_otp'))
                else:
                    flash('Error creating account. Please try again.', 'error')
                    return render_template('signup.html')

            except Exception as e:
                print(f'Error during registration: {e}')
                flash(f'Error during registration: {e}', 'error')
                return render_template('signup.html')
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        response = supabase.table('users').select('*').eq('email', email).execute()
        account = response.data[0] if response.data else None
        
        if account and check_password_hash(account['password'], password):
            session['loggedin'] = True
            session['id'] = account['id']
            session['name'] = account['name']
            return redirect(url_for('index'))
        else:
            flash('Incorrect username/password!')
    return render_template('login.html')

@app.route('/category/<category_name>', methods=["GET"])
def get_news_by_category(category_name):
    news_data = get_cached_news(category_name)
    if news_data:
        return jsonify({"articles": news_data})
    return jsonify({"error": "Unable to fetch news"})

@app.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('id', None)
    session.pop('name', None)
    return redirect(url_for('login'))

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    if 'email' not in session:
        return redirect(url_for('signup'))

    if request.method == 'POST':
        email = session.get('email')
        input_otp = request.form['otp']

        app.logger.info(f'Verifying OTP for email: {email}, OTP: {input_otp}')

        response = supabase.table('users').select('*').eq('email', email).eq('otp', input_otp).execute()
        account = response.data[0] if response.data else None

        if account:
            # Clear OTP after successful verification
            supabase.table('users').update({'otp': None}).eq('email', email).execute()
            flash('Your account has been verified successfully!', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid OTP. Please try again.', 'error')

    return render_template('verify_otp.html')

# Add error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True)

