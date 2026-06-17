# RiverLine Data Sources

## USGS National Water Information System (NWIS)
- **What:** Real-time and historical discharge (cfs), gage height
- **Coverage:** USGS stream gauges across Montana
- **API:** https://waterservices.usgs.gov/rest/IV-Service.html
- **Example site:** 06043500 (Gallatin River near Gallatin Gateway)

## NRCS SNOTEL
- **What:** Snow water equivalent (SWE), soil moisture — used as ML features
- **Coverage:** Mountain stations across SW Montana
- **API:** https://wcc.sc.egov.usda.gov/awdbWebService/services

## NOAA/NWS River Forecasts
- **What:** River stage and flow forecasts
- **Coverage:** NWS forecast points on major rivers
- **API:** https://api.water.noaa.gov/nwps/v1
