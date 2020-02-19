from setuptools import setup

import io

main_ns = {}
exec(open('dash_auth/version.py').read(), main_ns)

setup(
    name='dash_auth',
    version=main_ns['__version__'],
    author='Christopher Parmer',
    author_email='chris@plotly.com',
    packages=['dash_auth'],
    license='MIT',
    description='Dash Authorization Package.',
    long_description=io.open('README.md', encoding='utf-8').read(),
    install_requires=[
        'chart_studio>=1.0.0',
        'Flask>=1.0.2',
        'flask-compress',
        'flask-seasurf',
        'dash>=1.1.1',
        'requests',
        'retrying',
        'itsdangerous>=1.1.0',
        'ua_parser'
    ],
    include_package_data=True,
    url='https://plotly.com/dash',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'Framework :: Flask',
        'Intended Audience :: Developers',
        'Intended Audience :: Education',
        'Intended Audience :: Financial and Insurance Industry',
        'Intended Audience :: Healthcare Industry',
        'Intended Audience :: Manufacturing',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: MIT License',
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Database :: Front-Ends',
        'Topic :: Office/Business :: Financial :: Spreadsheet',
        'Topic :: Scientific/Engineering :: Visualization',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: Software Development :: Widget Sets'
    ]
)
