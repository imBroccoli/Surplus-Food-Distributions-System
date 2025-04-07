from django.contrib.messages.storage.session import SessionStorage

class SweetifyAwareSessionStorage(SessionStorage):
    """
    Custom session storage that properly handles Sweetify messages.
    This ensures that Sweetify messages are cleared after being displayed and integrated with Django messages.
    """
    def _get(self, *args, **kwargs):
        messages, all_retrieved = super()._get(*args, **kwargs)
        
        # Get any sweetify messages from the session
        sweetify_messages = self.request.session.get('sweetify', [])
        
        # Clear the sweetify messages from the session after retrieval
        if sweetify_messages:
            self.request.session['sweetify'] = []
            self.request.session.modified = True
        
        return messages, all_retrieved
    
    def add(self, level, message, extra_tags=''):
        """
        Make sure messages added through the Django messages framework 
        are also accessible to sweetify if they're added by views that don't use sweetify directly.
        """
        # Save the message using the parent implementation
        result = super().add(level, message, extra_tags)
        
        # Ensure the message is added to the session
        if result and hasattr(self.request, 'session'):
            self.request.session.modified = True
            
        return result
    
    def store(self, messages, response):
        """
        Ensure messages are properly stored in the session,
        especially when there's a redirect or a new session is created.
        """
        result = super().store(messages, response)
        
        # Make sure changes to the session are saved
        if hasattr(self.request, 'session'):
            self.request.session.modified = True
            
        return result