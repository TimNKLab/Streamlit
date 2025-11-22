"""Authentication logic module"""

class AuthManager:
    """Handles authentication logic"""
    
    def __init__(self, password="admin123"):
        self.password = password
    
    def verify_password(self, input_password):
        """Verify if the input password matches the stored password"""
        return input_password == self.password
    
    def is_authenticated(self, session_state):
        """Check if user is authenticated based on session state"""
        return session_state.get('authenticated', False)
    
    def set_authenticated(self, session_state, authenticated=True):
        """Set authentication status in session state"""
        session_state['authenticated'] = authenticated
    
    def logout(self, session_state):
        """Logout user by setting authenticated to False"""
        session_state['authenticated'] = False
