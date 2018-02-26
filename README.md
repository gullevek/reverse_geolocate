# Reverse GeoLocate for XMP Sidecar files

Reverse GeoLocate from XMP sidecar files with optional LightRoom DB read

This script will update any of the Country Code, Country, State, City and Location data that is missing in sidecard files. If a Lightroom DB is set, it will read any data from the database and fill in the fields before it tries to get the location name from google with the Latitude and Longitude found in either the XMP sidecar file or the LR database.

#### Installing and setting up

The script uses the following external non defauly python libraries
* xmp toolkit
* requests

install both with the pip3 command
```
pip3 install requests
pip3 install python-xmp-toolkit
```

XMP Toolkit also needs the [Exempi Library](http://libopenraw.freedesktop.org/wiki/Exempi). This one can be install via brew or macports directly.
See more information for [Python XMP Tool kit](http://python-xmp-toolkit.readthedocs.io/)

The scripts python3 enviroment path (#!...) needs to be set so it points to a valid python3 install.

## Command line arguments

reverse_geolocate.py [-h] -x
    [XMP SOURCE FOLDER [XMP SOURCE FOLDER ...]]
    [-l LIGHTROOM FOLDER] [-s]
    [-f <overwrite, location, city, state, country, countrycode>]
    [-g GOOGLE API KEY] [-o] [-e EMIL ADDRESS] [-n]
    [-v] [--debug] [--test]

### Arguments

Argument | Argument Value | Description
--- | --- | ---
-x, --xmp | XMP sidecar source folder or XMP sidecar file itself | Must given argument. It sets the path where the script will search for XMP sidecar files. It will traverse into subdirectories. A single XMP sidecar file can also be given. If the same file folder combination is found only one is processed.
-l, --lightroom | Lightroom DB base folder | The folder where the .lrcat file is located. Optional, if this is set, LR values are read before any Google maps connection is done. Fills the Latitude and Longitude and the location names. Lightroom data never overwrites data already set in the XMP sidecar file. It is recommended to have Lightroom write the XMP sidecar file before this script is run
-s, --strict | | Do strict check for Lightroom files and include the path into the check
-f, --field | Keyword: overwrite, location, city, state, country, countrycode | In the default no data is overwritten if it is already set. With the 'overwrite' flag all data is set new from the Google Maps location data. Other arguments are each of the location fields and if set only this field will be set. This can be combined with the 'overwrite' flag to overwrite already set data
-n, --nobackup | | Do not create a backup of XMP sidecar file when it is changed
-o, --openstreetmap | | Use OpenStreetMap instead of the default google maps
-e, --email | email address | For OpenStreetMap with a large number of access
-g, --google | Google Maps API Key | If available, to avoid the access limitations to the reverse location lookup
-v, --verbose | | More verbose output. Currently not used
--debug | | Full detailed debug output. Will print out alot of data
--test | | Does not write any changed back to the XMP sidecar file. For testing purposes

The script will created a backup of the current sidecar file named <original name>.BK.xmp in the same location as the original file.

If the Lightroom lookup is used without the --strict argument and several files with the same name are found, they will be skipped for usage.

#### Example

```
reverse_geolocate.py -x Photos/2017/01 -x Photos/2017/02 -l LightRoom/MyCatalogue -f overwrite -g <API KEY>
```

Will find all XMP sidecar files in both folders *Photos/2017/01* and *Photos/2017/02* and all folder below it. Uses the Lightroom database at *LightRoom/MyCatalogue*. The script will overwrite all data, even if it is already set

```
reverse_geolocate.py -x Photos/2017/01/Event-01/some_photo.xmp -f location
```

Only works on *some_photo.xmp* file and will only set the *location* field if it is not yet set.

### Google data priority

Based in the JSON return data the following fields are set in order. If one can not be found for a target set, the next one below is used

order | type | target set
--- | --- | ---
1 | country | Country, CountryCode
2 | administrative_area_level_1 | State
3 | administrative_area_level_2 | State
4 | locality | City
5 | sublocality_level_1 | Location
6 | sublocality_level_2 | Location
7 | route | Location

### OpenStreetMap data priority

order | type | target set
--- | --- | ---
1 | country_code | CountryCode
2 | country | Country
3 | state | State
4 | city | City
5 | city_district | City
6 | state_district | City
7 | county | Location
8 | town | Location
9 | suburb | Location
10 | hamlet | Location
11 | neighbourhood | Location
12 | raod | Location

### Script stats and errors on update

After the script is done the following overview will be printed

```
==============================
Found XMP Files       : 3
Updated               : 0
Skipped               : 2
New GeoLocation Google: 0
GeoLocation from Cache: 0
Failed for Reverse Geo: 1
GeoLoc from Lightroom : 0
No Lightroom data     : 0
```

If there are problems with getting data from the Google Maps API the complete errior sting will be printed

```
...
---> Photos/2017/02/some_file.xmp: Error in request: OVER_QUERY_LIMIT You have exceeded your daily request quota for this API. We recommend registering for a key at the Google Developers Console: https://console.developers.google.com/apis/credentials?project=_
(!) Could not geo loaction data [FAILED]
...
```

Also the files that could not be updated will be printed at the end of the run under the stats list

```
...
------------------------------
Files that failed to update:
Photos/2017/02/some_file.xmp
```

### Tested OS

This script has only been tested on macOS