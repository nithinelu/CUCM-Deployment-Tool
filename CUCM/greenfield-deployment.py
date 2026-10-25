import csv
from requests import Session
from requests.auth import HTTPBasicAuth
import csv
import pandas as pd
from lxml import etree
import getpass

from zeep import Client, Settings, Plugin, xsd
from zeep.transports import Transport
from zeep.exceptions import Fault
import sys


# Change to true to enable output of request/response headers and XML
DEBUG = False

# Collect Credentials and IP address
CUCM_ADDRESS = input("Enter CUCM IP address:- ")
USERNAME = input("Enter CUCM AXL Username:-")
PASSWORD = getpass.getpass()
CUCM_VERSION = input("Enter CUCM Versions:- ")

# The WSDL is a local file in the working directory, see README
WSDL_FILE = "schema/" + CUCM_VERSION + "/AXLAPI.wsdl"

# This class lets you view the incoming and outgoing http headers and XML


class MyLoggingPlugin(Plugin):
    def egress(self, envelope, http_headers, operation, binding_options):

        # Format the request body as pretty printed XML
        xml = etree.tostring(envelope, pretty_print=True, encoding="unicode")

        print(f"\nRequest\n-------\nHeaders:\n{http_headers}\n\nBody:\n{xml}")

    def ingress(self, envelope, http_headers, operation):

        # Format the response body as pretty printed XML
        xml = etree.tostring(envelope, pretty_print=True, encoding="unicode")

        print(f"\nResponse\n-------\nHeaders:\n{http_headers}\n\nBody:\n{xml}")


# The first step is to create a SOAP client session
session = Session()

# We avoid certificate verification by default
session.verify = False

# To enabled SSL cert checking (recommended for production)
# place the CUCM Tomcat cert .pem file in the root of the project
# and uncomment the line below

# session.verify = 'changeme.pem'


# Add Basic Auth credentials
session.auth = HTTPBasicAuth(USERNAME, PASSWORD)

# Create a Zeep transport and set a reasonable timeout value
transport = Transport(session=session, timeout=10)

# strict=False is not always necessary, but it allows zeep to parse imperfect XML
settings = Settings(strict=False, xml_huge_tree=True)

# If debug output is requested, add the MyLoggingPlugin callback
plugin = [MyLoggingPlugin()] if DEBUG else []

# Create the Zeep client with the specified settings
client = Client(WSDL_FILE, settings=settings, transport=transport, plugins=plugin)

# Create the Zeep service binding to AXL at the specified CUCM
service = client.create_service(
    "{http://www.cisco.com/AXLAPIService/}AXLAPIBinding",
    f"https://{CUCM_ADDRESS}:8443/axl/",
)

# Create Parition


def cucm_partition():
    try:
        respconf = service.addRoutePartition(lines)
    except Fault as err:
        print(f"Zeep error: addRoutePartition: { err }")
        sys.exit(1)
    print("\aaddRoutePartition response:\n")
    print(respconf, "\n")


partition = input("Configure  partition (Y/N):-")

if partition.lower() == "y":
    partiton_file_temp = csv.DictReader(open("partition.csv", encoding="utf-8-sig"))
    for lines in partiton_file_temp:
        cucm_partition()
else:
    input("Press Enter to continue...")


# Configure CSS

css = input("Configure Css (Y/N):-")

if css.lower() == "y":
    css_member = {}
    with open("css.csv") as csvfile:
        next(csvfile)
        reader = csv.reader(csvfile)
        css_increment = 1
        for css_name in reader:
            css = {
                "name": css_name[0],
                "description": css_name[1],
                "members": {"member": []},
            }

            css_increment += 1
            index_increment = 0
            with open("css.csv") as csvfile:
                next(csvfile)
                reader = csv.reader(csvfile)
                for row in reader:
                    index_increment += 1
                    if not row[css_increment]:
                        continue
                    css_member = {
                        "routePartitionName": row[css_increment],
                        "index": index_increment,
                    }
                    css["members"]["member"].append(css_member)

                # Execute the addCss request
                try:
                    resp = service.addCss(css)
                except Fault as err:
                    print(f"Zeep error: addCss: { err }")
                    sys.exit(1)

                print("\naddCss response:\n")
                print(resp, "\n")
else:
    input("Press Enter to continue...")

# Create Date & Time Group
date_time = {
    "name": "MUSCAT",
    "timeZone": "Asia/Muscat",
    "separator": "-",
    "dateformat": "M-D-Y",
    "timeFormat": "12-hour",
}


# Execute the addDateTimeGroup request
try:
    resp = service.addDateTimeGroup(date_time)
except Fault as err:
    print(f"Zeep error: addDateTimeGroup: { err }")
    sys.exit(1)

print("\naddDateTimeGroup response:\n")
print(resp, "\n")

# Configure UDT

udt_input = input("Do you want  to configure UniversalDeviceTemplate(Y/N):-")

if udt_input.lower() == "y":
    # Create  UDT
    udt = input("Enter UDT Name-")
    external_mask = input(" Enter the External Mask")
    add_udt = {
        "name": udt,
        "deviceDescription": "#FN# #LN# #EXT#",
        "devicePool": "Default",
        "deviceSecurityProfile": "Universal Device Template - Model-independent Security Profile",
        "sipProfile": "Standard SIP Profile",
        "phoneButtonTemplate": "Universal Device Template Button Layout",
        "commonPhoneProfile": "Standard Common Phone Profile",
        "softkeyTemplate": "Standard User",
        "mtpPreferredOriginatingCodec": "711alaw",
        "outboundCallRollover": "No Rollover",
        "phonePersonalization": "Enabled",
        "devicePool": "Default",
        "useTrustedRelayPoint": "Default",
        "devicePool": "Default",
        "certificateOperation": xsd.SkipValue,
        "authenticationMode": xsd.SkipValue,
        "keySize": xsd.SkipValue,
        "ecKeySize": xsd.SkipValue,
        "servicesProvisioning": xsd.SkipValue,
        "packetCaptureMode": xsd.SkipValue,
        "mlppIndication": xsd.SkipValue,
        "mlppPreemption": xsd.SkipValue,
        "dndOption": "Use Common Phone Profile Setting",
        "blfPresenceGroup": xsd.SkipValue,
        "blfAudibleAlertSettingPhoneBusy": xsd.SkipValue,
        "blfAudibleAlertSettingPhoneIdle": xsd.SkipValue,
        "location": "Hub_None",
        "deviceMobilityMode": xsd.SkipValue,
        "joinAcrossLines": xsd.SkipValue,
        "alwaysUsePrimeLine": xsd.SkipValue,
        "alwaysUsePrimeLineForVoiceMessage": xsd.SkipValue,
        "singleButtonBarge": xsd.SkipValue,
        "builtInBridge": xsd.SkipValue,
        "privacy": xsd.SkipValue,
        "lines": {"line": []},
    }
    line_details = {
        "index": "1",
        "label": "#FN# #LN# #EXT#",
        "display": "#FN# #LN# #EXT#",
        "e164Mask": external_mask,
        "ringSetting": "Ring",
        "dirn": xsd.SkipValue,
        "maxNumCalls": "4",
        "busyTrigger": "2",
        "callerName": "true",
    }

    add_udt["lines"]["line"].append(line_details)
    try:
        respconf = service.addUniversalDeviceTemplate(add_udt)
    except Fault as err:
        print(f"Zeep error: addUniversalDeviceTemplate: { err }")
        sys.exit(1)

    print("\aaddUniversalDeviceTemplate response:\n")
    print(respconf, "\n")

    input("Press Enter to continue...")
else:
    input("Press Enter to continue...")

# Create Universal Line Template
ult_input = input("Do you want  to configure Universal Line  Template(Y/N):-")

if ult_input.lower() == "y":
    # Create  UDT
    ult = input("Press Enter to ULT  Name-")
    add_ult = {
        "name": "ULT",
        "urgentPriority": xsd.SkipValue,
        "lineDescription": "#FN# #LN# ",
        "routePartition": xsd.SkipValue,
        "voiceMailProfile": "Default",
        "callingSearchSpace": "CSS_Internal",
        "alertingName": "#FirstName# #LastName#",
        "extCallControlProfile": xsd.SkipValue,
        "blfPresenceGroup": "Standard Presence group",
        "callPickupGroup": xsd.SkipValue,
        "partyEntranceTone": xsd.SkipValue,
        "autoAnswer": xsd.SkipValue,
        "rejectAnonymousCall": xsd.SkipValue,
        "userHoldMohAudioSource": xsd.SkipValue,
        "networkHoldMohAudioSource": xsd.SkipValue,
        "aarDestinationMask": xsd.SkipValue,
        "aarGroup": xsd.SkipValue,
        "retainDestInCallFwdHistory": "t",
        "forwardDestAllCalls": xsd.SkipValue,
        "primaryCssForwardingAllCalls": xsd.SkipValue,
        "secondaryCssForwardingAllCalls": xsd.SkipValue,
        "CssActivationPolicy": xsd.SkipValue,
        "fwdDestExtCallsWhenNotRetrieved": xsd.SkipValue,
        "cssFwdExtCallsWhenNotRetrieved": xsd.SkipValue,
        "fwdDestInternalCallsWhenNotRetrieved": xsd.SkipValue,
        "cssFwdInternalCallsWhenNotRetrieved": xsd.SkipValue,
        "parkMonitorReversionTime": xsd.SkipValue,
        "target": xsd.SkipValue,
        "mlppCss": xsd.SkipValue,
        "mlppNoAnsRingDuration": xsd.SkipValue,
        "confidentialAccess": xsd.SkipValue,
        "confidentialAccessMode": xsd.SkipValue,
        "holdReversionRingDuration": xsd.SkipValue,
        "holdReversionNotificationInterval": xsd.SkipValue,
        "busyIntCallsDestination": xsd.SkipValue,
        "busyIntCallsCss": xsd.SkipValue,
        "busyExtCallsDestination": xsd.SkipValue,
        "busyExtCallsCss": xsd.SkipValue,
        "noAnsIntCallsDestination": xsd.SkipValue,
        "noAnsIntCallsCss": xsd.SkipValue,
        "noAnsExtCallsDestination" "noAnsExtCallsCss": xsd.SkipValue,
        "noCoverageIntCallsDestination": xsd.SkipValue,
        "noCoverageIntCallsCss": xsd.SkipValue,
        "noCoverageExtCallsDestination": xsd.SkipValue,
        "noCoverageExtCallsCss": xsd.SkipValue,
        "unregisteredIntCallsDestination": xsd.SkipValue,
        "unregisteredIntCallsCss": xsd.SkipValue,
        "unregisteredExtCallsDestination": xsd.SkipValue,
        "unregisteredExtCallsCss": xsd.SkipValue,
        "ctiFailureDestination": xsd.SkipValue,
        "ctiFailureCss": xsd.SkipValue,
        "callControlAgentProfile": xsd.SkipValue,
        "noAnswerRingDuration": "60",
        "enterpriseAltNum": xsd.SkipValue,
    }

    try:
        respconf = service.addUniversalLineTemplate(add_ult)
    except Fault as err:
        print(f"Zeep error: addUniversalDeviceTemplate: { err }")
        sys.exit(1)

    print("\aaddUniversalDeviceTemplate response:\n")
    print(respconf, "\n")

    input("Press Enter to continue...")
else:
    input("Press Enter to continue...")


# Create a  Region


region = {"name": "HQ REGION", "relatedRegions": {"relatedRegion": []}}

# Create a relatedRegion sub object
related_region = {
    "regionName": "HQ REGION",
    "bandwidth": "64 kbps",
    "videoBandwidth": "512",
    "lossyNetwork": "Low Loss",
    "codecPreference": "Factory Default low loss",
    "immersiveVideoBandwidth": "2000000000",
}

related_default_region = {
    "regionName": "Default",
    "bandwidth": "64 kbps",
    "videoBandwidth": "512",
    "lossyNetwork": "Low Loss",
    "codecPreference": "Factory Default low loss",
    "immersiveVideoBandwidth": "2000000000",
}

# Add the relatedRegion to the region.relatedRegions array
region["relatedRegions"]["relatedRegion"].append(related_region)
region["relatedRegions"]["relatedRegion"].append(related_default_region)


# Execute the addRegion request
try:
    resp = service.addRegion(region)
except Fault as err:
    print(f"Zeep error: addRegion: { err }")
    sys.exit(1)

print("\naddRegion response:\n")
print(resp, "\n")

input("Press Enter to continue...")

Conf_yes_no = input("Do you need to configure ConferanceNow(Y/N):-")

if Conf_yes_no.lower() == "y":
    # Create a test ConferenceNow
    conf_now_num = input("Press Enter to confernace Now Number:-")
    conferenceNow = {
        "conferenceNowNumber": conf_now_num,
        "description": "test",
        "maxWaitTimeForHost": "15",
    }
    try:
        respconf = service.addConferenceNow(conferenceNow)
    except Fault as err:
        print(f"Zeep error: addConferenceNow: { err }")
        sys.exit(1)

    print("\addConferenceNow response:\n")
    print(respconf, "\n")

    input("Press Enter to continue...")
else:
    input("Press Enter to continue...")

# Create MRG

mrg = {
    "name": "MRG",
    "description": "MEDIA RESOURCE GROUP",
    "multicast": "f",
    "members": {
        "member": {
            "deviceName": "ANN_2",
        }
    },
}


# Execute the addMediaResourceGroup request
try:
    resp = service.addMediaResourceGroup(mrg)
except Fault as err:
    print(f"Zeep error: addMediaResourceGroup: { err }")
    sys.exit(1)

print("\naddMediaResourceGroup response:\n")
print(resp, "\n")


domain = input("Enter the gateway Domain for MGCP :-")
description = input("Enter the gateway Description:- ")


gateway = {
    "domainName": domain,
    "description": description,
    "product": "Cisco ISR 4321",
    "protocol": "MGCP",
    "callManagerGroupName": "Default",
    "units": {"unit": []},
}

# Create a relatedRegion sub object
unit_name = {"index": "0", "product": "ISR-2NIM-MBRD", "subunits": {"subunit": []}}

subunit_name = {"index": "1", "product": "NIM-1MFT-T1E1-E1", "beginPort": "0"}
unit_name["subunits"]["subunit"].append(subunit_name)
gateway["units"]["unit"].append(unit_name)


# Execute the addRegion request
try:
    resp = service.addGateway(gateway)
except Fault as err:
    print(f"Zeep error: addGateway: { err }")
    sys.exit(1)

print("\naddRegion response:\n")
print(resp, "\n")

input("Press Enter to continue...")


ucm.add_route_group(
    route_group="hollywood-rg",
    distribution_algorithm="Circular",
    members=[("america-online-sip"), ("h323")],
)

# Create a  Route List
route_list_name = input("Enter the Route List Name:- ")
route_list = {"name": route_list_name, "callManagerGroupName": "Default"}

# Execute the addRouteList request
try:
    resp = service.addRouteList(route_list)
except Fault as err:
    print(f"Zeep error: addRouteList: { err }")
    sys.exit(1)

print("\naddRouteList response:\n")
print(resp, "\n")

input("Press Enter to continue...")

# create a  Route Pattern
route_pattern = {
    "pattern": "1234567890",
    "routePartitionName": None,
    "blockEnable": False,
    "useCallingPartyPhoneMask": "Default",
    "dialPlanName": None,
    "digitDiscardInstructionName": None,
    "networkLocation": "OnNet",
    "prefixDigitsOut": None,
    "routeFilterName": None,
    "destination": {"routeListName": "testRouteList"},
}

# Execute the addRoutePattern request
try:
    resp = service.addRoutePattern(route_pattern)
except Fault as err:
    print(f"Zeep error: addMediaRaddRoutePatternesourceList: { err }")
    sys.exit(1)

print("\naddRoutePattern response:\n")
print(resp, "\n")

input("Press Enter to continue...")

# Cleanup the objects we just created
try:
    resp = service.removeRoutePattern(pattern="1234567890", routePartitionName=None)
except Fault as err:
    print(f"Zeep error: remremoveRoutePatternoveDevicePool: { err }")
    sys.exit(1)

print("\nremoveRoutePattern response:")
print(resp, "\n")

try:
    resp = service.removeRouteList(name="testRouteList")
except Fault as err:
    print(f"Zeep error: removeMeremoveRouteListdiaResourceList: { err }")
    sys.exit(1)

print("\nremoveRouteList response:")
print(resp, "\n")
