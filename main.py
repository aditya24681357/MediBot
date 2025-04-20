from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import requests
import json
import os
from models import db, User

app = Flask(__name__)
CORS(app)

# Configuration
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Change this to a secure secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///medibot.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

OLLAMA_API_URL = "http://localhost:11434"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def needs_more_info(symptoms):
    """Check if we need more information based on the symptoms"""
    # If it's already a detailed response from the form, don't ask for more info
    if any(key in symptoms for key in ["Duration:", "Severity:", "Pattern:", "Original symptoms:"]):
        return False
        
    # List of vague symptoms that need more details
    vague_symptoms = [
        "pain", "ache", "hurt", "discomfort", "not feeling well",
        "sick", "unwell", "bad", "weird", "strange", "odd",
        "symptoms", "problem", "issue", "head", "stomach", "throat"
    ]
    
    symptoms_lower = symptoms.lower()
    
    # Check if the symptoms are too vague
    for vague in vague_symptoms:
        if vague in symptoms_lower:
            return True
            
    # Check if the description is too short
    if len(symptoms.split()) < 4:
        return True
        
    return False

def create_medical_prompt(symptoms):
    # If this is a detailed form response, parse it differently
    if "Original symptoms:" in symptoms:
        return f"""You are a medical assistant. Provide treatment recommendations for these symptoms:

{symptoms}

Format your response EXACTLY like this, using bullet points and keeping each point brief and clear:

POSSIBLE MEDICINES:
• Medicine 1 (Brand name) - Exact dosage and frequency
• Medicine 2 (Brand name) - Exact dosage and frequency
• Medicine 3 (Brand name) - Exact dosage and frequency

PRECAUTIONS:
• Safety measure 1
• Warning sign 1
• Lifestyle recommendation 1
• Activity to avoid 1

WHERE TO FIND:
• Pharmacy type 1
• Location type 1
• Prescription information
• Emergency option if needed

Keep your response focused and structured exactly as shown above, using bullet points (•) for each item."""
    else:
        return f"""You are a medical assistant. Provide treatment recommendations for these symptoms: {symptoms}

Format your response EXACTLY like this, using bullet points and keeping each point brief and clear:

POSSIBLE MEDICINES:
• Medicine 1 (Brand name) - Exact dosage and frequency
• Medicine 2 (Brand name) - Exact dosage and frequency
• Medicine 3 (Brand name) - Exact dosage and frequency

PRECAUTIONS:
• Safety measure 1
• Warning sign 1
• Lifestyle recommendation 1
• Activity to avoid 1

WHERE TO FIND:
• Pharmacy type 1
• Location type 1
• Prescription information
• Emergency option if needed

Keep your response focused and structured exactly as shown above, using bullet points (•) for each item."""

def create_maps_link(location=None):
    """Create a Google Maps link for nearby pharmacies"""
    base_url = "https://www.google.com/maps/search/pharmacies"
    if location and isinstance(location, dict) and 'latitude' in location and 'longitude' in location:
        return f"{base_url}/@{location['latitude']},{location['longitude']},15z"
    return base_url

def format_ollama_response(response_text, location=None):
    """Format the Ollama response into HTML with our styling"""
    # Split the response into sections
    sections = {
        "POSSIBLE MEDICINES:": "🏥",
        "PRECAUTIONS:": "⚠️",
        "WHERE TO FIND:": "🔍"
    }
    
    html_response = '<div class="medical-response">'
    
    current_section = None
    section_content = []
    
    for line in response_text.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        # Check if this line is a section header
        is_header = False
        for header in sections:
            if header in line:
                # If we were building a previous section, add it to the response
                if current_section and section_content:
                    html_response += f'''
    <div class="response-section">
        <h3>{sections[current_section]} {current_section}</h3>
        <ul>
'''
                    for item in section_content:
                        if item.strip():
                            html_response += f'            <li>{item}</li>\n'
                    html_response += '        </ul>\n    </div>\n'
                
                current_section = header
                section_content = []
                is_header = True
                break
                
        if not is_header and current_section:
            # Clean up the line
            cleaned_line = line.strip('- ').strip()
            if cleaned_line:
                section_content.append(cleaned_line)
    
    # Add the last section
    if current_section and section_content:
        html_response += f'''
    <div class="response-section">
        <h3>{sections[current_section]} {current_section}</h3>
        <ul>
'''
        for item in section_content:
            if item.strip():
                html_response += f'            <li>{item}</li>\n'
        html_response += '        </ul>\n'
        
        # Add Google Maps link after WHERE TO FIND section
        if current_section == "WHERE TO FIND:":
            maps_link = create_maps_link(location)
            html_response += f'''
        <div class="maps-link">
            <a href="{maps_link}" target="_blank" class="google-maps-btn">
                <img src="https://maps.google.com/mapfiles/ms/icons/red-dot.png" alt="Maps Icon" width="20" height="20">
                View Nearby Pharmacies on Google Maps
            </a>
        </div>
'''
        html_response += '    </div>\n'
    
    html_response += '</div>'
    return html_response

def get_model_response(prompt, location=None):
    try:
        print("Attempting to connect to Ollama...")
        # First try Ollama API
        response = requests.get(f"{OLLAMA_API_URL}/api/tags", timeout=5)
        print(f"Ollama status check response: {response.status_code}")
        
        if response.status_code == 200:
            # Use a more direct prompt style
            detailed_prompt = f"""Provide medical advice for: {prompt}

You must respond in this exact format:

POSSIBLE MEDICINES:
1. Medicine name (Brand name) - dosage and frequency
2. Medicine name (Brand name) - dosage and frequency
3. Medicine name (Brand name) - dosage and frequency

PRECAUTIONS:
- Safety step 1
- Safety step 2
- Safety step 3

WHERE TO FIND:
- Location 1
- Location 2
- Location 3

Do not include any other text. Start directly with POSSIBLE MEDICINES:"""
            
            print("Sending request to Ollama model...")
            
            payload = {
                "model": "medllama2",
                "prompt": detailed_prompt,
                "stream": False,
                "temperature": 0.3,  # Lower temperature for more focused responses
                "top_p": 0.9,
                "max_tokens": 1000
            }
            
            print("Payload:", payload)
            
            try:
                response = requests.post(f"{OLLAMA_API_URL}/api/generate", json=payload, timeout=30)
                print(f"Response status: {response.status_code}")
                print(f"Response content: {response.text[:500]}")
                
                if response.status_code == 200:
                    response_data = response.json()
                    if isinstance(response_data, dict) and "response" in response_data:
                        model_response = response_data["response"].strip()
                        
                        # If response doesn't start with our format, add it
                        if not model_response.startswith("POSSIBLE MEDICINES:"):
                            model_response = "POSSIBLE MEDICINES:\n" + model_response
                        
                        # Ensure all sections exist
                        if "PRECAUTIONS:" not in model_response:
                            model_response += "\n\nPRECAUTIONS:\n- Monitor symptoms\n- Rest and stay hydrated\n- Seek medical attention if symptoms worsen"
                        
                        if "WHERE TO FIND:" not in model_response:
                            model_response += "\n\nWHERE TO FIND:\n- Local pharmacies\n- Drug stores\n- Consult healthcare provider"
                        
                        print(f"Formatted response: {model_response[:200]}")
                        return format_ollama_response(model_response, location)
                
            except Exception as e:
                print(f"Request error: {str(e)}")
    
    except Exception as e:
        print(f"Ollama API error: {str(e)}")

    print("Model response failed, using fallback system...")
    # If all attempts fail, use our fallback system
    symptoms_lower = prompt.lower()
    response_sections = {
        "medicines": [],
        "precautions": [],
        "locations": []
    }

    # Parse the detailed form data if available
    form_data = {}
    if "Original symptoms:" in prompt:
        lines = prompt.split('\n')
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                form_data[key.strip()] = value.strip()

    # Add form-specific recommendations if available
    if form_data:
        severity = form_data.get("Severity", "").split('/')[0]
        if severity.isdigit() and int(severity) >= 7:
            response_sections["precautions"].append("Given the high severity, consider seeking immediate medical attention")
        
        duration = form_data.get("Duration", "")
        if any(word in duration.lower() for word in ["week", "month", "year"]):
            response_sections["precautions"].append("Due to the long duration, consultation with a healthcare provider is recommended")

    # Add default locations with map link placeholder
    default_locations = [
        "Available at nearby pharmacies (click map link below)",
        "Most medications available at major drugstore chains",
        "Check 24-hour pharmacies for urgent needs",
        "Consider pharmacy delivery services if needed",
        "For prescription medications, consult with a healthcare provider first"
    ]
    response_sections["locations"].extend(default_locations)

    # Format the response in HTML with a note about consulting a healthcare provider
    html_response = '<div class="medical-response">'
    
    html_response += '''
    <div class="response-section">
        <h3>⚠️ IMPORTANT NOTE:</h3>
        <p>For your specific symptoms, it\'s recommended to consult with a healthcare provider for proper diagnosis and treatment. They can provide personalized medical advice and appropriate medication recommendations.</p>
    </div>

    <div class="response-section">
        <h3>⚠️ GENERAL PRECAUTIONS:</h3>
        <ul>
            <li>Monitor your symptoms and keep a log of any changes</li>
            <li>If symptoms worsen or persist, seek medical attention</li>
            <li>Stay hydrated and get adequate rest</li>
            <li>Consider keeping a symptom diary to share with your healthcare provider</li>
        </ul>
    </div>

    <div class="response-section">
        <h3>🔍 WHERE TO FIND HELP:</h3>
        <ul>
'''
    for location_item in set(response_sections["locations"]):
        html_response += f'            <li>{location_item}</li>\n'
    html_response += '        </ul>\n'
    
    # Add Google Maps link
    maps_link = create_maps_link(location)
    html_response += f'''
        <div class="maps-link">
            <a href="{maps_link}" target="_blank" class="google-maps-btn">
                <img src="https://maps.google.com/mapfiles/ms/icons/red-dot.png" alt="Maps Icon" width="20" height="20">
                View Nearby Pharmacies on Google Maps
            </a>
        </div>
'''
    html_response += '    </div>\n</div>'

    return html_response

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match')
            return redirect(url_for('register'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('register'))
        
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password')
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def home():
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    data = request.json
    symptoms = data.get('symptoms', '')
    location = data.get('location', None)
    
    if not symptoms:
        return jsonify({'error': 'No symptoms provided'}), 400
    
    # Check if we need more information only for initial symptoms
    if needs_more_info(symptoms) and "Original symptoms:" not in symptoms:
        return jsonify({
            'needsMoreInfo': True,
            'message': 'Please provide more details about your symptoms.'
        })
    
    response_text = get_model_response(symptoms, location)
    
    formatted_response = {
        'answer': response_text.strip() if response_text else "I apologize, but I couldn't process your symptoms properly. Please try again.",
        'needsMoreInfo': False
    }
    
    return jsonify(formatted_response)

if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists('instance'):
            os.makedirs('instance')
        db.create_all()
    app.run(debug=True)