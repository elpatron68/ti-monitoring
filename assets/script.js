function toggleAccordion(clickedAccordion) {
    var currentContentHeight = window.getComputedStyle(clickedAccordion.parentElement.getElementsByClassName('accordion-element-content')[0]).height;
    // close clicked accordion element
    if (currentContentHeight != '0px') {
        clickedAccordion.parentElement.getElementsByClassName('accordion-element-content')[0].style.height = '0px';
        clickedAccordion.style.backgroundColor = '';
        clickedAccordion.getElementsByClassName('expand-collapse-icon')[0].textContent = '+';
    }
    // open clicked accordion element and close all other accordion elements
    else {
        var accordionElements = document.getElementsByClassName('accordion-element');
        Array.from(accordionElements).forEach(function(element) {
            title = element.getElementsByClassName('accordion-element-title')[0];
            content = element.getElementsByClassName('accordion-element-content')[0];
            if (title == clickedAccordion) {
                title.style.backgroundColor = 'lightgrey';
                content.style.height =  content.scrollHeight + 'px';
                title.getElementsByClassName('expand-collapse-icon')[0].textContent = '–';
            }
            else {
                title.style.backgroundColor = '';
                content.style.height = '0px';
                title.getElementsByClassName('expand-collapse-icon')[0].textContent = '+';
            }
        });
    }
}

window.addEventListener('click', function(event) {
    const clickedElement = event.target;
    if (clickedElement.classList.contains('accordion-element-title')) {
        toggleAccordion(clickedElement);
    }
});

// add favicon to head (defensive)
try {
    var headEl = document.getElementsByTagName('head')[0];
    if (headEl && headEl.appendChild) {
        var favicon_png = document.createElement('link');
        favicon_png.setAttribute('rel', 'apple-touch-icon');
        favicon_png.setAttribute('type', 'image/png');
        favicon_png.setAttribute('href', 'assets/favicon.png');
        headEl.appendChild(favicon_png);

        var favicon_svg = document.createElement('link');
        favicon_svg.setAttribute('rel', 'icon');
        favicon_svg.setAttribute('type', 'image/svg+xml');
        favicon_svg.setAttribute('href', 'assets/logo.svg');
        headEl.appendChild(favicon_svg);
    }
} catch (e) {
    // noop
}

// Dash clientside helper for notifications test
(function() {
    var clientside = window.dash_clientside = window.dash_clientside || {};
    var ns = clientside["notifications"] = clientside["notifications"] || {};

    ns["sendTestNotification"] = function(n_clicks, url) {
        console.log("sendTestNotification called with:", n_clicks, url);
        if (!n_clicks || n_clicks < 1) {
            console.log("No clicks or clicks < 1");
            return window.dash_clientside.no_update;
        }
        if (!url || !String(url).trim()) {
            console.log("No URL provided");
            return "Bitte geben Sie eine Apprise-URL ein.";
        }
        try {
            console.log("Making fetch request to /api/notifications/test");
            console.log("Document cookies:", document.cookie);
            return fetch('/api/notifications/test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ url: String(url).trim(), title: 'TI-Monitoring Test (UI)', body: 'UI-Test über /api/notifications/test' })
            }).then(function(resp) {
                console.log("Received response:", resp);
                console.log("Response status:", resp.status);
                console.log("Response headers:", [...resp.headers.entries()]);
                
                if (!resp.ok) {
                    if (resp.status === 401) {
                        console.log("Received 401 Unauthorized - session may have expired");
                        return 'Fehler: Nicht authentifiziert. Bitte melden Sie sich erneut an.';
                    }
                    throw new Error('HTTP error ' + resp.status);
                }
                return resp.json();
            }).then(function(data) {
                console.log("Received data:", data);
                if (data && data.status === 'ok') {
                    return 'Test-Benachrichtigung erfolgreich gesendet.';
                }
                return 'Fehler: ' + (data && (data.error || data.status) || 'unbekannt');
            }).catch(function(err) {
                console.log("Fetch error:", err);
                return 'Fehler: ' + String(err);
            });
        } catch (e) {
            console.log("Exception:", e);
            return 'Fehler: ' + String(e);
        }
    };

    ns["requestOtp"] = function(n_clicks, email) {
        if (!n_clicks || n_clicks < 1) {
            return window.dash_clientside.no_update;
        }
        if (!email || !String(email).trim()) {
            return 'Bitte E-Mail eingeben.';
        }
        return fetch('/api/auth/request_otp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ email: String(email).trim() })
        }).then(function(resp) { return resp.json(); }).then(function(data) {
            if (data && (data.status === 'ok' || data.sent === true)) {
                return 'OTP wurde gesendet. Prüfen Sie Ihren Posteingang.';
            }
            return 'Fehler beim Senden des OTP: ' + (data && (data.error || data.status) || 'unbekannt');
        }).catch(function(err) { return 'Fehler: ' + String(err); });
    };

    ns["verifyOtp"] = function(n_clicks, email, otp) {
        if (!n_clicks || n_clicks < 1) {
            return window.dash_clientside.no_update;
        }
        if (!email || !String(email).trim()) {
            return { authenticated: false };
        }
        if (!otp || !String(otp).trim()) {
            return { authenticated: false };
        }
        return fetch('/api/auth/verify_otp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ email: String(email).trim(), code: String(otp).trim() })
        }).then(function(resp) { 
            if (resp && resp.ok) {
                // Store the email in localStorage for later use
                try {
                    localStorage.setItem('user_email', String(email).trim());
                } catch (e) {
                    console.log("Could not store email in localStorage:", e);
                }
                return { authenticated: true, email: String(email).trim() };
            }
            return resp.json();
        }).then(function(data) {
            if (data && data.status === 'ok') {
                return { authenticated: true, email: String(email).trim() };
            }
            return { authenticated: false };
        }).catch(function() { return { authenticated: false }; });
    };

    ns["checkSession"] = function(n_intervals) {
        return fetch('/api/auth/session', {
            method: 'GET',
            credentials: 'include'
        }).then(function(resp) {
            if (resp && resp.ok) { 
                // Try to get email from localStorage if available
                var email = null;
                try {
                    email = localStorage.getItem('user_email');
                } catch (e) {
                    console.log("Could not retrieve email from localStorage:", e);
                }
                return { authenticated: true, email: email };
            }
            return { authenticated: false };
        }).catch(function() { return { authenticated: false }; });
    };

    ns["deleteAccount"] = function(n_clicks) {
        if (!n_clicks || n_clicks < 1) {
            return window.dash_clientside.no_update;
        }
        return fetch('/api/account', {
            method: 'DELETE',
            credentials: 'include'
        }).then(function(resp) { return resp.json(); }).then(function(data) {
            if (data && data.status === 'ok') {
                return { msg: 'Konto wurde gelöscht. Bitte Seite neu laden.', ok: true };
            }
            return { msg: 'Löschen fehlgeschlagen: ' + (data && (data.error || 'unbekannt')), ok: false };
        }).catch(function(err) {
            return { msg: 'Löschen fehlgeschlagen: ' + String(err), ok: false };
        });
    };

    ns["logout"] = function(n_clicks) {
        if (!n_clicks || n_clicks < 1) {
            return window.dash_clientside.no_update;
        }
        // Make a request to the logout endpoint to clear the session cookie
        return fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'include'
        }).then(function(resp) {
            return { authenticated: false };
        }).catch(function() {
            return { authenticated: false };
        });
    };
    
    // Profile deletion function - fixed version
    ns["deleteProfile"] = function(n_clicks, button_id) {
        // Check if the button was actually clicked
        if (!n_clicks || n_clicks < 1) {
            return window.dash_clientside.no_update;
        }
        
        // Extract profile ID from button ID
        // Button ID format: {"type":"delete-profile-button","index":PROFILE_ID}
        try {
            var buttonIdObj = JSON.parse(button_id);
            var profileId = buttonIdObj.index;
            
            if (!profileId) {
                return window.dash_clientside.no_update;
            }
            
            // Confirm deletion
            if (!confirm('Möchten Sie dieses Profil wirklich löschen?')) {
                return window.dash_clientside.no_update;
            }
            
            return fetch('/api/notifications/profiles/' + profileId, {
                method: 'DELETE',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' }
            }).then(function(resp) {
                if (resp && resp.ok) {
                    // Reload the page to refresh the profile list
                    window.location.reload();
                    return 'Profil gelöscht.';
                } else {
                    return 'Fehler beim Löschen des Profils.';
                }
            }).catch(function(err) {
                return 'Fehler beim Löschen des Profils: ' + String(err);
            });
        } catch (e) {
            return 'Fehler beim Verarbeiten der Anfrage: ' + String(e);
        }
    };
})();