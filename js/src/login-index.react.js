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
        const {
            oauth_client_id,
            plotly_domain,
            requests_pathname_prefix
        } = CONFIG;
        /*
         * There are a few things to consider when constructing the redirect_uri:
         * - Since Dash apps can have URLs (https://plot.ly/dash/urls), e.g.
         *   `/page-1/another-page`, and so just appending the /_oauth-redirect
         *   API path to the end of the current URL (window.location.href) isn't
         *   safe because the API endpoint is `/_oauth-redirect` not e.g.
         *   `/page-1/another-page/_oauth-redirect`
         * - Dash apps may be served by a proxy which prefixes a path to them.
         *   This is what happens in Plotly On-Premise's Path-Based-Routing.
         *   For example, the dash app may be rendered under `/my-dash-app/`
         *   In this case, we can't just use window.location.origin because there
         *   that would skip this pathname prefix. The config variable
         *   `requests_pathname_prefix` contains this prefix (`/my-dash-app/`)
         *   and is used to prefix all of the front-end API endpoints.
         * - Dash apps may be served on a subdomain. window.location.origin picks
         *   up the subdomain.
         */
        return (
            `${plotly_domain}/o/authorize/?response_type=token&` +
            `client_id=${oauth_client_id}&` +
            `redirect_uri=${window.location.origin}${requests_pathname_prefix}${REDIRECT_URI_PATHNAME}`
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
            <div id="dash-auth--login__container" className="container">
                <h2>{'Dash'}</h2>

                <h4>
                    {'Log in to Plotly to continue'}
                </h4>

                <button id="dash-auth--login__button" onClick={this.oauthPopUp}>
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

ReactDOM.render(<Login/>, document.getElementById('react-entry-point'));
