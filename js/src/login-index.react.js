/* global window:true, document:true */

import React, {Component} from 'react';
import ReactDOM from 'react-dom';

require('../styles/application.scss');

const CONFIG = JSON.parse(document.getElementById('_auth-config').textContent);
window.CONFIG = CONFIG;
const REDIRECT_URI_PATHNAME = '_oauth-redirect';

// http://stackoverflow.com/questions/4068373/center-a-popup-window-on-screen
const PopupCenter = (url, title, w, h) => {
    // Fixes dual-screen position
    const screenLeft = window.screenLeft;
    const screenTop = window.screenTop;

    const width = window.innerWidth;
    const height = window.innerHeight;

    const left = ((width / 2) - (w / 2)) + screenLeft;
    const top = ((height / 2) - (h / 2)) + screenTop;
    const popupWindow = window.open(
        url, title,
        ('scrollbars=yes,width=' + w +
         ', height=' + h + ', top=' + top +
         ', left=' + left)
    );
    return popupWindow;
};

/**
 * Login displays an interface that guides the user through an oauth flow.
 * - Clicking on a login button will launch a new window with the plot.ly
 *   oauth url
 * - plot.ly will redirect that window to defined redirect URL when complete
 * - The <OauthRedirect/> component will render the oauth redirect page
 * - When the <OauthRedirect/> window is closed, <Login/> will call its
 *   `onClosed` prop
 */
class Login extends Component {
    constructor(props) {
        super(props);
        this.buildOauthUrl = this.buildOauthUrl.bind(this);
        this.oauthPopUp = this.oauthPopUp.bind(this);
    }

    buildOauthUrl() {
        const {oauth_client_id, plotly_domain} = CONFIG;
        return (
            `${plotly_domain}/o/authorize/?response_type=token&` +
            `client_id=${oauth_client_id}&` +
            `redirect_uri=${window.location.origin}/${REDIRECT_URI_PATHNAME}`
        );
    }

    oauthPopUp() {
        const popupWindow = PopupCenter(
            this.buildOauthUrl(), 'Authorization', '500', '500'
        );
        if (window.focus) {
            popupWindow.focus();
        }
        window.popupWindow = popupWindow;
        const interval = setInterval(() => {
            if(popupWindow.closed) {
                clearInterval(interval);
                // Check if successful?
                window.location.reload();
            }
        }, 100);
    }

    render() {
        const {plotly_domain} = CONFIG;
        return (
            <div className="container">
                <h2>{'Dash'}</h2>

                <h4>
                    {'Log in to Plotly to continue'}
                </h4>

                <button onClick={this.oauthPopUp}>
                    {'Log in'}
                </button>

                <div className="caption">
                    <span>
                        {`This dash app requires a plotly login to view.
                          Don't have an account yet?`}
                    </span>
                    <a
                       href={`${plotly_domain}/accounts/login/?action=signup`}>
                        {' Create an account '}
                    </a>
                    <span>
                    {` (it's free)
                      and then request access from the owner of this app.`}
                    </span>
                </div>
            </div>
        );
    }
}

ReactDOM.render(<Login/>, document.getElementById('react-root'));
