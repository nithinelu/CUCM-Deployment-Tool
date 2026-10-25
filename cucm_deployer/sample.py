"""Example greenfield build (Oman HQ) used for the sample workbook.

Same dial plan idea as the original partition.csv / css.csv: four calling
privileges (Internal, Landline, GSM, International), each CSS adding one
more partition.
"""

PT = "PT_Internal"

SAMPLE = {
    "Date Time Groups": [
        {"Name": "DTG_Muscat", "Time Zone": "Asia/Muscat", "Separator": "-",
         "Date Format": "D-M-Y", "Time Format": "12-hour"},
    ],
    "Regions": [{"Name": "RG_HQ"}, {"Name": "RG_Branch"}],
    "Region Relations": [
        {"Region": "RG_HQ", "Related Region": "RG_HQ", "Audio Bandwidth": "64 kbps",
         "Video Bandwidth kbps": 512},
        {"Region": "RG_HQ", "Related Region": "RG_Branch", "Audio Bandwidth": "8 kbps",
         "Video Bandwidth kbps": 384},
        {"Region": "RG_Branch", "Related Region": "RG_Branch", "Audio Bandwidth": "64 kbps"},
    ],
    "Locations": [
        {"Name": "LOC_HQ", "Link To Location": "Hub_None"},
        {"Name": "LOC_Branch", "Link To Location": "Hub_None", "Link Audio kbps": 512},
    ],
    "CallManager Groups": [
        {"Name": "CMG_HQ", "Members (in order)": "CM_CUCM-SUB1;CM_CUCM-PUB"},
    ],
    "Partitions": [
        {"Name": "PT_Internal", "Description": "Internal Calling Group"},
        {"Name": "PT_Landline", "Description": "Landline Calling Group"},
        {"Name": "PT_GSM", "Description": "GSM Calling Group"},
        {"Name": "PT_International", "Description": "International Calling Group"},
        {"Name": "PT_Xlate", "Description": "Translations"},
    ],
    "Calling Search Spaces": [
        {"Name": "CSS_Internal", "Description": "Internal Calling Privilege",
         "Partitions (in order)": "PT_Internal"},
        {"Name": "CSS_Landline", "Description": "Landline Calling Privilege",
         "Partitions (in order)": "PT_Internal;PT_Landline"},
        {"Name": "CSS_GSM", "Description": "GSM Calling Privilege",
         "Partitions (in order)": "PT_Internal;PT_Landline;PT_GSM"},
        {"Name": "CSS_International", "Description": "International Calling Privilege",
         "Partitions (in order)": "PT_Internal;PT_Landline;PT_GSM;PT_International"},
        {"Name": "CSS_PSTN_In", "Description": "Inbound from PSTN",
         "Partitions (in order)": "PT_Xlate;PT_Internal"},
    ],
    "Media Resource Groups": [
        {"Name": "MRG_HQ", "Description": "HQ media resources",
         "Media Resources": "ANN_2;CFB_2;MOH_2;MTP_2"},
    ],
    "Media Resource Lists": [
        {"Name": "MRGL_HQ", "Media Resource Groups (in order)": "MRG_HQ"},
    ],
    "SRST References": [
        {"Name": "SRST_Branch", "IP Address": "10.20.0.1"},
    ],
    "Device Pools": [
        {"Name": "DP_HQ", "CallManager Group": "CMG_HQ", "Date Time Group": "DTG_Muscat",
         "Region": "RG_HQ", "Media Resource List": "MRGL_HQ", "Location": "LOC_HQ",
         "SRST Reference": "Disable", "Local Route Group": "RG_PSTN_HQ"},
        {"Name": "DP_Branch", "CallManager Group": "CMG_HQ", "Date Time Group": "DTG_Muscat",
         "Region": "RG_Branch", "Media Resource List": "MRGL_HQ", "Location": "LOC_Branch",
         "SRST Reference": "SRST_Branch"},
    ],
    "SIP Trunks": [
        {"Name": "SIPT_CUBE_HQ", "Description": "To HQ CUBE (Omantel)", "Device Pool": "DP_HQ",
         "Location": "LOC_HQ", "Inbound CSS": "CSS_PSTN_In",
         "Destinations": "10.10.0.10:5060;10.10.0.11:5060"},
    ],
    "MGCP Gateways": [
        {"Domain Name": "HQ-ISR4321", "Description": "HQ E1 PRI gateway",
         "Product": "Cisco ISR 4321", "CallManager Group": "CMG_HQ",
         "Module in Slot 0": "ISR-2NIM-MBRD", "Subunits": "1:NIM-1MFT-T1E1-E1"},
    ],
    "Route Groups": [
        {"Name": "RG_PSTN_HQ", "Distribution Algorithm": "Top Down",
         "Devices (in order)": "SIPT_CUBE_HQ"},
    ],
    "Route Lists": [
        {"Name": "RL_PSTN", "Description": "PSTN via local route group",
         "CallManager Group": "CMG_HQ",
         "Route Groups (in order)": "Standard Local Route Group;RG_PSTN_HQ"},
    ],
    "Route Patterns": [
        {"Pattern": "9.2XXXXXXX", "Partition": "PT_Landline", "Description": "Oman landline",
         "Route List": "RL_PSTN", "Discard Digits": "PreDot"},
        {"Pattern": "9.[79]XXXXXXX", "Partition": "PT_GSM", "Description": "Oman GSM",
         "Route List": "RL_PSTN", "Discard Digits": "PreDot"},
        {"Pattern": "9.00!", "Partition": "PT_International", "Description": "International",
         "Route List": "RL_PSTN", "Discard Digits": "PreDot"},
        {"Pattern": "9.00!#", "Partition": "PT_International",
         "Description": "International (# end of dialing)", "Route List": "RL_PSTN",
         "Discard Digits": "PreDot Trailing-#"},
        {"Pattern": "9999", "Partition": "PT_Internal", "Description": "Emergency",
         "Route List": "RL_PSTN", "Urgent Priority": "Yes"},
    ],
    "Translation Patterns": [
        {"Pattern": "2441XXXX", "Partition": "PT_Xlate", "Description": "DID to extension",
         "CSS": "CSS_Internal", "Called Party Mask": "1XXX"},
    ],
    "Calling Party Xforms": [],
    "Called Party Xforms": [],
    "Voicemail Pilots": [
        {"Pilot Number": "1999", "CSS": "CSS_Internal", "Description": "Unity Connection"},
    ],
    "Voicemail Profiles": [
        {"Name": "VMP_CUC", "Description": "Unity Connection", "Pilot Number": "1999",
         "Pilot CSS": "CSS_Internal"},
    ],
    "Call Pickup Groups": [
        {"Name": "CPG_Reception", "Pickup Number": "1900", "Partition": PT},
    ],
    "Conference Now": [
        {"Number": "1800", "Partition": PT, "Description": "Conference Now",
         "Max Wait For Host (min)": 15},
    ],
    "Universal Line Templates": [
        {"Name": "ULT_HQ", "Partition": PT, "Line CSS": "CSS_GSM",
         "Voicemail Profile": "VMP_CUC"},
    ],
    "Universal Device Templates": [
        {"Name": "UDT_HQ", "Device Pool": "DP_HQ", "Device CSS": "CSS_Internal",
         "Location": "LOC_HQ", "External Phone Mask": "2441XXXX"},
    ],
    "Directory Numbers": [
        {"Directory Number": "1001", "Partition": PT, "Description": "Ahmed Al Balushi",
         "Alerting Name": "Ahmed Al Balushi", "Line CSS": "CSS_GSM",
         "Voicemail Profile": "VMP_CUC", "Forward CSS": "CSS_Internal",
         "Forward Busy to VM": "Yes", "Forward No Answer to VM": "Yes"},
        {"Directory Number": "1002", "Partition": PT, "Description": "Reception",
         "Alerting Name": "Reception", "Line CSS": "CSS_Landline",
         "Call Pickup Group": "CPG_Reception"},
    ],
    "End Users": [
        {"User ID": "ahmed.balushi", "First Name": "Ahmed", "Last Name": "Al Balushi",
         "Email": "ahmed.balushi@example.om", "Telephone Number": "1001",
         "Access Control Groups": "Standard CCM End Users;Standard CTI Enabled",
         "Controlled Devices": "SEP00AABBCC1001;CSFABALUSHI",
         "Primary Extension": "1001/PT_Internal"},
    ],
    "Phones": [
        {"Device Name": "SEP00AABBCC1001", "Description": "Ahmed Al Balushi 8845",
         "Product": "Cisco 8845", "Device Pool": "DP_HQ", "Device CSS": "CSS_Internal",
         "Location": "LOC_HQ", "Phone Button Template": "Standard 8845 SIP",
         "Security Profile": "Cisco 8845 - Standard SIP Non-Secure Profile",
         "Owner User ID": "ahmed.balushi", "Lines": "1001/PT_Internal",
         "Line 1 Display": "Ahmed Al Balushi", "Line 1 Label": "1001",
         "Line 1 External Mask": "2441XXXX"},
        {"Device Name": "CSFABALUSHI", "Description": "Ahmed Al Balushi Jabber",
         "Product": "Cisco Unified Client Services Framework", "Device Pool": "DP_HQ",
         "Device CSS": "CSS_Internal", "Phone Button Template": "Standard Client Services Framework",
         "Security Profile": "Cisco Unified Client Services Framework - Standard SIP Non-Secure Profile",
         "Owner User ID": "ahmed.balushi", "Lines": "1001/PT_Internal"},
    ],
    "Line Groups": [
        {"Name": "LG_Reception", "Members (in order)": "1002/PT_Internal;1001/PT_Internal"},
    ],
    "Hunt Lists": [
        {"Name": "HL_Reception", "CallManager Group": "CMG_HQ",
         "Line Groups (in order)": "LG_Reception"},
    ],
    "Hunt Pilots": [
        {"Pattern": "1000", "Partition": PT, "Description": "Reception hunt",
         "Hunt List": "HL_Reception", "Alerting Name": "Reception",
         "Forward No Answer To": "1999", "Forward No Answer CSS": "CSS_Internal"},
    ],
}
