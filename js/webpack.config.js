var path = require('path');
var webpack = require('webpack');

module.exports = {
  devtool: 'eval',
  entry: {
    'login': './src/login-index.react.js',
    'oauth-redirect': './src/oauth-redirect-index.react.js'
  },
  output: {
    path: path.join(__dirname, '..', 'dash_auth'),
    filename: '[name].js',
  },
  module: {
    loaders: [
      {
        test: /react\.jsx?$/,
        loaders: ['babel-loader'],
        include: path.join(__dirname, 'src')
      },
      {
        test: /\.scss$/,
        loaders: ["style-loader", "css-loader", "sass-loader"]
      }
    ]
  }
}
