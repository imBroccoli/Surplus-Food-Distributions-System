from django import template
from django.conf import settings
from django.utils.safestring import mark_safe
import json

register = template.Library()

@register.simple_tag(takes_context=True)
def sweetify(context, nonce=None):
    """
    A fixed implementation of the sweetify template tag that ensures proper JavaScript syntax
    for SweetAlert calls.
    """
    try:
        request = context.get('request')
        if not request:
            return ""
            
        # Get messages from session but don't pop immediately
        opts = request.session.get("sweetify", None)
        library = getattr(settings, "SWEETIFY_SWEETALERT_LIBRARY", "sweetalert2")
        
        if not opts:
            return ""
            
        if isinstance(opts, list):
            if library == "sweetalert":
                raise RuntimeError("multiple alerts are currently not supported in sweetalert")
                
            # Handle multiple alerts
            scripts = []
            for opt in opts:
                # Handle persistent messages
                if isinstance(opt, dict) and opt.get('persistent') is True and 'timer' not in opt:
                    opt['timer'] = None
                    opt['showConfirmButton'] = True
                
                if isinstance(opt, str):
                    opt = {'text': opt}
                
                # Ensure options are properly formatted
                if isinstance(opt, dict):
                    scripts.append(f"""
                        sweetify.fire({{ 
                            title: "{opt.get('title', '')}",
                            text: "{opt.get('text', '')}",
                            icon: "{opt.get('icon', 'success')}",
                            timer: {opt.get('timer', 'null')},
                            position: "{opt.get('position', 'center')}",
                            showConfirmButton: {str(opt.get('showConfirmButton', True)).lower()},
                            confirmButtonText: "{opt.get('confirmButtonText', 'OK')}",
                            timerProgressBar: {str(opt.get('timerProgressBar', True)).lower()},
                            toast: {str(opt.get('toast', False)).lower()},
                            ...{json.dumps(opt)}
                        }});
                    """)
            
            # Only remove messages after they've been processed
            request.session.pop("sweetify", None)
            request.session.modified = True
            
            return mark_safe(f"""
                <script nonce="{nonce if nonce else ''}">
                    document.addEventListener('DOMContentLoaded', function() {{
                        {' '.join(scripts)}
                    }});
                </script>
            """)
        
        return ""
    except Exception as e:
        logger.error(f"Error in sweetify template tag: {str(e)}")
        return ""