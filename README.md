script.myepisodes
=================

Kodi plugin for [MyEpisodes](https://www.myepisodes.com)

This plugin will set TV shows episodes you've seen as watched on MyEpisodes.
It will also add the the TV show to your account if it was not already there.

This was done mainly because I'm too lazy to do it by hand and I watch 98% of
my video through Kodi.

Needs Kodi 20 or later.

setup
=====

The plugin talks to the MyEpisodes JSON API, which authenticates with an API
key rather than a password.

**Upgrading from 3.x needs nothing from you.** On its first start the plugin
trades the username and password it already holds for an API key, stores the
key, and carries on.

For a fresh install:

1. Sign in at [myepisodes.com](https://www.myepisodes.com/frontpage/).
2. Go to Account, then API Keys, and create a key with the `write` scope.
3. Paste the key (it starts with `myeps_`) into the plugin's API Key setting.

The key is a credential: it grants the same access to your account that the
plugin needs, and you can revoke it at any time from the same page.

build
=====
If you really want to build it, here is a simple script to do so:
```sh
#!/bin/bash

dest=script.myepisodes
version=$(grep "^\s\+version" addon.xml | cut -f2 -d'"')

if [ -d $dest ]; then
    rm -r $dest
fi

mkdir $dest
cp addon.xml $dest/
cp *.txt $dest/
cp icon.png $dest/
cp *.py $dest/
cp -r resources $dest/

if [ -f $dest-$version.zip ]; then
    rm $dest-$version.zip
fi

zip -r $dest-$version.zip $dest
rm -r $dest
````
It will create a zip file that you can install directly within Kodi.

install
=======

Using the GUI of Kodi, choose to install your plugin as a zip file, find your
zip file, and you're done !

download
========
If you can't or don't want to build this plugin, look at the release tab.
You can download the last plugin from there.

[Download the latest release](https://github.com/maximeh/script.myepisodes/releases/latest)
and pick the `script.myepisodes-<version>.zip` asset.

known issues
============

MyEpisodes matches a search term literally, so "Mr Robot" does not reach
"Mr. Robot". The plugin works around this by searching a single distinctive
word and comparing the punctuation-stripped names itself, which covers the
titles it reads out of filenames. If it still reports that it can't find your
show, add the show on the MyEpisodes website and the plugin will pick it up
from your list. If that's not the case either, feel free to open an issue.
