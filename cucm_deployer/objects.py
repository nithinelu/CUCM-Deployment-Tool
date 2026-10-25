"""What each Excel sheet configures on CUCM.

A Sheet maps Excel columns to an AXL object. Columns point at a dotted AXL path
inside the object ("destination.routeListName") or use a builder function for
list-type cells such as "P_Internal;P_Local" (ordered members).

Any extra column whose header starts with "axl:" is passed straight through,
e.g. "axl:callForwardAll.destination" on the Directory Numbers sheet, so every
AXL field of every CUCM version can be set without changing this file.

DEPLOY_PLAN is the dependency order used for Add/Update (Delete runs in reverse).
"""

from .schema import vkey

ACTIONS = ["Add", "Update", "Add/Update", "Delete", "Skip"]
BOOL_CHOICES = ["Yes", "No"]


# --------------------------------------------------------------------------
# cell helpers
# --------------------------------------------------------------------------
def items(value):
    """'A; B\\nC' -> ['A', 'B', 'C']"""
    return [p.strip() for p in str(value).replace("\n", ";").split(";") if p.strip()]


def dn_split(value):
    """'1001/P_Internal' -> ('1001', 'P_Internal'); '1001' -> ('1001', '')."""
    pattern, _, partition = str(value).partition("/")
    return pattern.strip(), partition.strip()


def set_path(body, path, value):
    parts = path.split(".")
    cur = body
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = cur[p] = {}
        cur = nxt
    cur[parts[-1]] = value


# --------------------------------------------------------------------------
# builders: f(body, value, ctx) - ctx has "version" (AXL) and "row" (all cells)
# --------------------------------------------------------------------------
def members(container, item, name_field, order_field=None, start=1, extra=None):
    """Ordered member list from 'A;B;C' (schema.py puts the child tags in XSD order)."""
    def build(body, value, ctx):
        out = []
        for i, name in enumerate(items(value)):
            m = {name_field: name}
            if order_field:
                m[order_field] = str(i + start)
            m.update(extra or {})
            out.append(m)
        body[container] = {item: out}
    return build


def copy_to(*paths):
    """One cell -> several AXL fields."""
    def build(body, value, ctx):
        for p in paths:
            set_path(body, p, str(value))
    return build


def line_group_members(body, value, ctx):
    out = []
    for i, entry in enumerate(items(value)):
        pattern, partition = dn_split(entry)
        out.append({"lineSelectionOrder": str(i + 1),
                    "directoryNumber": {"pattern": pattern, "routePartitionName": partition}})
    body["members"] = {"member": out}


def sip_destinations(body, value, ctx):
    """'10.1.1.1:5060;10.1.1.2' -> destinations (port defaults to 5060)."""
    out = []
    for i, entry in enumerate(items(value)):
        host, port = (entry.split(":") + ["5060"])[:2] if entry.count(":") <= 1 else (entry, "5060")
        out.append({"addressIpv4": host.strip(), "port": port.strip() or "5060",
                    "sortOrder": str(i + 1)})
    if vkey(ctx["version"]) < (9, 0):             # 8.5: one destination only
        if out:
            body["destinationAddress"] = out[0]["addressIpv4"]
            body["destinationport"] = out[0]["port"]
        return
    body["destinations"] = {"destination": out}


def gateway_subunits(body, value, ctx):
    unit = body.setdefault("units", {}).setdefault("unit", {"index": "0"})
    subs = []
    for entry in items(value):
        idx, _, product = entry.partition(":")
        subs.append({"index": idx.strip(), "product": product.strip(), "beginPort": "0"})
    unit["subunits"] = {"subunit": subs}


def gateway_module(body, value, ctx):
    unit = body.setdefault("units", {}).setdefault("unit", {"index": "0"})
    unit["product"] = str(value).strip()


def phone_lines(body, value, ctx):
    out = []
    for i, entry in enumerate(items(value)):
        pattern, partition = dn_split(entry)
        out.append({"index": str(i + 1),
                    "dirn": {"pattern": pattern, "routePartitionName": partition}})
    body["lines"] = {"line": out}


def first_line(attr):
    def build(body, value, ctx):
        lines = body.get("lines", {}).get("line")
        if not lines:
            ctx["warn"].append(f"'{attr}' ignored - no Lines given")
            return
        lines[0][attr] = str(value)
    return build


def speed_dials(body, value, ctx):
    """'2001:Reception; 2002:Security' -> speeddials"""
    out = []
    for i, entry in enumerate(items(value)):
        dirn, _, label = entry.partition(":")
        out.append({"dirn": dirn.strip(), "label": label.strip() or dirn.strip(), "index": str(i + 1)})
    body["speeddials"] = {"speeddial": out}


def phone_finish(body, ctx):
    """Associate the owner with the phone's lines (needed for presence / Jabber)."""
    owner = body.get("ownerUserName")
    if owner and ctx.get("action") != "update":
        for line in body.get("lines", {}).get("line", []):
            line.setdefault("associatedEndusers", {"enduser": {"userId": owner}})


def user_devices(body, value, ctx):
    body["associatedDevices"] = {"device": items(value)}


def user_groups(body, value, ctx):
    body["associatedGroups"] = {"userGroup": [{"name": g} for g in items(value)]}


def user_primary(body, value, ctx):
    pattern, partition = dn_split(value)
    body["primaryExtension"] = {"pattern": pattern, "routePartitionName": partition}


def line_forward_css(body, value, ctx):
    for k in ("callForwardAll", "callForwardBusy", "callForwardBusyInt", "callForwardNoAnswer",
              "callForwardNoAnswerInt", "callForwardNoCoverage", "callForwardNoCoverageInt",
              "callForwardOnFailure", "callForwardNotRegistered", "callForwardNotRegisteredInt"):
        body.setdefault(k, {})["callingSearchSpaceName"] = str(value)


def line_forward_vm(*keys):
    def build(body, value, ctx):
        for k in keys:
            body.setdefault(k, {})["forwardToVoiceMail"] = value
    return build


def line_noanswer_duration(body, value, ctx):
    for k in ("callForwardNoAnswer", "callForwardNoAnswerInt"):
        body.setdefault(k, {})["duration"] = str(value)


def local_route_group(body, value, ctx):
    if vkey(ctx["version"]) < (10, 0):
        body["localRouteGroupName"] = str(value)
    else:
        body["localRouteGroup"] = {"name": "Standard Local Route Group", "value": str(value)}


def udt_line(attr, old_attr):
    """UDT line settings moved into lines.line in AXL 12.0."""
    def build(body, value, ctx):
        if vkey(ctx["version"]) >= (12, 0):
            line = body.setdefault("lines", {}).setdefault("line", {"index": "1"})
            line[attr] = str(value)
        else:
            body[old_attr] = str(value)
    return build


def by_version(new_path, old_path, since):
    """Field renamed in AXL `since` (older clusters get old_path)."""
    def build(body, value, ctx):
        set_path(body, new_path if vkey(ctx["version"]) >= vkey(since) else old_path, value)
    return build


def hunt_forward(which, field):
    def build(body, value, ctx):
        fwd = body.setdefault(which, {"usePersonalPreferences": "false"})
        fwd[field] = str(value)
    return build


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------
class F:
    """One Excel column."""

    def __init__(self, header, path=None, kind="text", req=False, hint="", default=None,
                 choices=None, build=None, width=None, key=False, post=False):
        self.header = header
        self.path = path
        self.kind = kind            # text | bool | int
        self.req = req              # required for Add
        self.hint = hint
        self.default = default      # used on Add when the cell is blank
        self.choices = choices      # list, or "enum" = take from the AXL schema
        self.build = build
        self.width = width or max(14, min(36, len(header) + 4))
        self.key = key              # identifies the object for Update / Delete
        self.post = post            # feeds a deferred field (applied in the later update step)


class Sheet:
    def __init__(self, name, obj, tag, fields, key=("name",), const=None, about="",
                 list_criteria=None, deferred=(), finish=None, kind="object", min_version=None,
                 key_extra=None):
        self.name = name
        self.obj = obj              # "Css" -> addCss / updateCss / removeCss / listCss
        self.tag = tag              # element inside addXxx, e.g. "css"
        self.fields = fields
        self.key = key
        self.key_extra = key_extra or {}    # extra (empty) key elements for update/remove
        self.const = const or {}    # fixed values sent on Add
        self.about = about
        self.list_criteria = list_criteria if list_criteria is not None else key[0]
        self.deferred = set(deferred)   # top-level fields applied in a later update step
        self.finish = finish
        self.kind = kind            # object | relations
        self.min_version = min_version

    def op(self, verb):
        return f"{verb}{self.obj}"

    def field(self, header):
        h = header.strip().rstrip("*").strip().lower()
        return next((f for f in self.fields if f.header.lower() == h), None)


Y = "bool"
I = "int"
PATTERN_KEY = {"dialPlanName": "", "routeFilterName": ""}

SHEETS = [
    Sheet("Date Time Groups", "DateTimeGroup", "dateTimeGroup", [
        F("Name", "name", req=True, key=True, hint="e.g. DTG_Muscat"),
        F("Time Zone", "timeZone", req=True, choices="enum", hint="e.g. Asia/Muscat", width=24),
        F("Separator", "separator", default="-", choices=["-", "/", "."]),
        F("Date Format", "dateformat", default="D-M-Y",
          choices=["M-D-Y", "D-M-Y", "Y-M-D", "M-D-YA", "D-M-YA", "YA-M-D"]),
        F("Time Format", "timeFormat", default="12-hour", choices=["12-hour", "24-hour"]),
    ], about="Date/Time Groups used by Device Pools."),

    Sheet("Regions", "Region", "region", [
        F("Name", "name", req=True, key=True, hint="e.g. RG_HQ"),
    ], about="Regions. Codec / bandwidth between regions goes on the 'Region Relations' sheet."),

    Sheet("Region Relations", "Region", "region", [
        F("Region", "name", req=True, key=True, hint="Region being configured"),
        F("Related Region", "regionName", req=True, hint="Same or other region"),
        F("Audio Bandwidth", "bandwidth", default="64 kbps",
          hint="e.g. 64 kbps / 32 kbps / 8 kbps / Use System Default"),
        F("Video Bandwidth kbps", "videoBandwidth", kind=I, default="384"),
        F("Immersive Video kbps", "immersiveVideoBandwidth", kind=I, default="2000000000"),
        F("Lossy Network", "lossyNetwork", default="Use System Default", choices="enum"),
        F("Codec Preference List", "codecPreference", default="Use System Default",
          hint="Use System Default / Factory Default low loss / Factory Default lossy"),
    ], kind="relations", list_criteria="",
       about="One row per region pair. Applied with updateRegion after the regions exist."),

    Sheet("Locations", "Location", "location", [
        F("Name", "name", req=True, key=True, hint="e.g. LOC_HQ"),
        F("Within Audio kbps", None, kind=I, default="0", hint="0 = Unlimited",
          build=by_version("withinAudioBandwidth", "kbits", "9.0")),
        F("Within Video kbps", None, kind=I, default="0", hint="0 = Unlimited",
          build=by_version("withinVideoBandwidth", "videoKbits", "9.0")),
        F("Within Immersive kbps", "withinImmersiveKbits", kind=I, default="0", hint="0 = Unlimited"),
        F("Link To Location", "betweenLocations.betweenLocation.locationName", default="Hub_None"),
        F("Link Weight", "betweenLocations.betweenLocation.weight", kind=I, default="50"),
        F("Link Audio kbps", "betweenLocations.betweenLocation.audioBandwidth", kind=I, default="0"),
        F("Link Video kbps", "betweenLocations.betweenLocation.videoBandwidth", kind=I, default="0"),
        F("Link Immersive kbps", "betweenLocations.betweenLocation.immersiveBandwidth", kind=I,
          default="0"),
    ], about="Enhanced Locations CAC. Each location is linked to one other (normally Hub_None)."),

    Sheet("CallManager Groups", "CallManagerGroup", "callManagerGroup", [
        F("Name", "name", req=True, key=True, hint="e.g. CMG_SUB1_SUB2"),
        F("Members (in order)", None, req=True, build=members("members", "member", "callManagerName",
                                                               "priority", 1),
          hint="CallManager names, ; separated, e.g. CM_SUB1;CM_SUB2", width=34),
        F("TFTP Default", "tftpDefault", kind=Y, default="No"),
    ]),

    Sheet("Partitions", "RoutePartition", "routePartition", [
        F("Name", "name", req=True, key=True, hint="e.g. PT_Internal"),
        F("Description", "description"),
        F("Time Schedule", "timeScheduleIdName", hint="optional"),
        F("Use Originating Device Time Zone", "useOriginatingDeviceTimeZone", kind=Y),
        F("Time Zone", "timeZone", choices="enum"),
    ]),

    Sheet("Calling Search Spaces", "Css", "css", [
        F("Name", "name", req=True, key=True, hint="e.g. CSS_Internal"),
        F("Description", "description"),
        F("Partitions (in order)", None, build=members("members", "member", "routePartitionName",
                                                       "index", 1),
          hint="; separated, top = first searched", width=44),
    ]),

    Sheet("Media Resource Groups", "MediaResourceGroup", "mediaResourceGroup", [
        F("Name", "name", req=True, key=True, hint="e.g. MRG_HQ"),
        F("Description", "description"),
        F("Use Multicast for MOH", "multicast", kind=Y, default="No"),
        F("Media Resources", None, req=True, build=members("members", "member", "deviceName"),
          hint="Device names ; separated, e.g. ANN_2;CFB_2;MOH_2;MTP_2", width=40),
    ]),

    Sheet("Media Resource Lists", "MediaResourceList", "mediaResourceList", [
        F("Name", "name", req=True, key=True, hint="e.g. MRGL_HQ"),
        F("Media Resource Groups (in order)", None, req=True,
          build=members("members", "member", "mediaResourceGroupName", "order", 0), width=40),
    ]),

    Sheet("SRST References", "Srst", "srst", [
        F("Name", "name", req=True, key=True, hint="e.g. SRST_HQ"),
        F("IP Address", "ipAddress", req=True),
        F("Port", "port", kind=I, default="2000"),
        F("SIP Network/IP", "SipNetwork"),
        F("SIP Port", "SipPort", kind=I, default="5060"),
    ]),

    Sheet("Device Pools", "DevicePool", "devicePool", [
        F("Name", "name", req=True, key=True, hint="e.g. DP_HQ"),
        F("CallManager Group", "callManagerGroupName", req=True, default="Default"),
        F("Date Time Group", "dateTimeSettingName", req=True),
        F("Region", "regionName", req=True),
        F("Media Resource List", "mediaResourceListName"),
        F("Location", "locationName"),
        F("SRST Reference", "srstName", default="Disable",
          hint="Disable / Use Default Gateway / SRST name"),
        F("Network Locale", "networkLocale", choices="enum"),
        F("Local Route Group", None, build=local_route_group,
          hint="Route Group used as 'Standard Local Route Group'"),
        F("AAR CSS", "automatedAlternateRoutingCssName"),
        F("Device Mobility CSS", "mobilityCssName"),
        F("Physical Location", "physicalLocationName"),
        F("Device Mobility Group", "deviceMobilityGroupName"),
        F("Calling Party Transformation CSS", "callingPartyTransformationCSS"),
    ]),

    Sheet("SIP Trunks", "SipTrunk", "sipTrunk", [
        F("Name", "name", req=True, key=True, hint="e.g. SIPT_CUBE_HQ"),
        F("Description", "description"),
        F("Device Pool", "devicePoolName", req=True),
        F("Location", "locationName", req=True, default="Hub_None"),
        F("Media Resource List", "mediaResourceListName"),
        F("Inbound CSS", "callingSearchSpaceName"),
        F("Rerouting CSS", "rerouteCallingSearchSpaceName"),
        F("Refer CSS", "referCallingSearchSpaceName"),
        F("Security Profile", "securityProfileName", req=True, default="Non Secure SIP Trunk Profile",
          width=28),
        F("SIP Profile", "sipProfileName", req=True, default="Standard SIP Profile"),
        F("Destinations", None, req=True, build=sip_destinations,
          hint="ip:port ; separated, e.g. 10.10.1.1:5060;10.10.1.2:5060", width=34),
        F("Run On All Active Nodes", "runOnEveryNode", kind=Y, default="Yes"),
        F("Media Termination Point Required", "mtpRequired", kind=Y, default="No"),
        F("DTMF Signaling", "dtmfSignalingMethod", default="No Preference", choices="enum"),
        F("Presence Group", "presenceGroupName", default="Standard Presence group"),
        F("Normalization Script", "sipNormalizationScriptName"),
        F("Unknown Prefix", "unknownPrefix"),
    ], const={"product": "SIP Trunk", "class": "Trunk", "protocol": "SIP",
              "protocolSide": "Network"}),

    Sheet("MGCP Gateways", "Gateway", "gateway", [
        F("Domain Name", "domainName", req=True, key=True, hint="Router hostname(.domain), e.g. HQ-ISR"),
        F("Description", "description"),
        F("Product", "product", req=True, default="Cisco ISR 4321", hint="e.g. Cisco ISR 4331"),
        F("CallManager Group", "callManagerGroupName", req=True, default="Default"),
        F("Module in Slot 0", None, build=gateway_module, default="ISR-2NIM-MBRD",
          hint="e.g. ISR-2NIM-MBRD / ISR-3NIM-MBRD", width=24),
        F("Subunits", None, build=gateway_subunits,
          hint="subunit:module ; separated, e.g. 1:NIM-1MFT-T1E1-E1", width=30),
    ], key=("domainName",), const={"protocol": "MGCP"},
       about="MGCP gateway + modules. PRI endpoints are configured afterwards in CCMAdmin."),

    Sheet("Route Groups", "RouteGroup", "routeGroup", [
        F("Name", "name", req=True, key=True, hint="e.g. RG_PSTN_HQ"),
        F("Distribution Algorithm", "distributionAlgorithm", default="Top Down", choices="enum"),
        F("Devices (in order)", None, req=True,
          build=members("members", "member", "deviceName", "deviceSelectionOrder", 1,
                        extra={"port": "0"}),
          hint="Trunk / gateway endpoint names ; separated", width=36),
    ]),

    Sheet("Route Lists", "RouteList", "routeList", [
        F("Name", "name", req=True, key=True, hint="e.g. RL_PSTN_HQ"),
        F("Description", "description"),
        F("CallManager Group", "callManagerGroupName", req=True, default="Default"),
        F("Enabled", "routeListEnabled", kind=Y, default="Yes"),
        F("Run On All Active Nodes", "runOnEveryNode", kind=Y),
        F("Route Groups (in order)", None, req=True,
          build=members("members", "member", "routeGroupName", "selectionOrder", 1),
          hint="; separated. 'Standard Local Route Group' allowed", width=36),
    ]),

    Sheet("Route Patterns", "RoutePattern", "routePattern", [
        F("Pattern", "pattern", req=True, key=True, hint="e.g. 9.[2-9]XXXXXXX"),
        F("Partition", "routePartitionName", key=True),
        F("Description", "description"),
        F("Route List", "destination.routeListName", hint="Use this OR Gateway/Trunk"),
        F("Gateway/Trunk", "destination.gatewayName"),
        F("Block Pattern", "blockEnable", kind=Y, default="No"),
        F("Urgent Priority", "patternUrgency", kind=Y),
        F("Use External Phone Mask", "useCallingPartyPhoneMask", default="Default", choices="enum"),
        F("Calling Party Mask", "callingPartyTransformationMask"),
        F("Calling Party Prefix", "callingPartyPrefixDigits"),
        F("Discard Digits", "digitDiscardInstructionName", hint="e.g. PreDot"),
        F("Called Party Mask", "calledPartyTransformationMask"),
        F("Prefix Digits", "prefixDigitsOut"),
        F("Network Location", "networkLocation", default="OffNet", choices="enum"),
        F("Provide Outside Dial Tone", "provideOutsideDialtone", kind=Y),
    ], key=("pattern", "routePartitionName"), key_extra=PATTERN_KEY, list_criteria="pattern"),

    Sheet("Translation Patterns", "TransPattern", "transPattern", [
        F("Pattern", "pattern", req=True, key=True),
        F("Partition", "routePartitionName", key=True),
        F("Description", "description"),
        F("CSS", "callingSearchSpaceName"),
        F("Use Originator's CSS", "useOriginatorCss", kind=Y),
        F("Block Pattern", "blockEnable", kind=Y, default="No"),
        F("Urgent Priority", "patternUrgency", kind=Y, default="Yes"),
        F("Use External Phone Mask", "useCallingPartyPhoneMask", default="Default", choices="enum"),
        F("Calling Party Mask", "callingPartyTransformationMask"),
        F("Calling Party Prefix", "callingPartyPrefixDigits"),
        F("Discard Digits", "digitDiscardInstructionName"),
        F("Called Party Mask", "calledPartyTransformationMask"),
        F("Prefix Digits", "prefixDigitsOut"),
        F("Provide Outside Dial Tone", "provideOutsideDialtone", kind=Y, default="No"),
    ], key=("pattern", "routePartitionName"), key_extra=PATTERN_KEY,
       const={"usage": "Translation"}, list_criteria="pattern"),

    Sheet("Calling Party Xforms", "CallingPartyTransformationPattern",
          "callingPartyTransformationPattern", [
              F("Pattern", "pattern", req=True, key=True),
              F("Partition", "routePartitionName", key=True),
              F("Description", "description"),
              F("Calling Party Mask", "callingPartyTransformationMask"),
              F("Prefix Digits", "callingPartyPrefixDigits"),
              F("Discard Digits", "digitDiscardInstructionName"),
              F("Use External Phone Mask", "useCallingPartyPhoneMask", default="Default",
                choices="enum"),
              F("Calling Line ID Presentation", "callingLinePresentationBit", choices="enum"),
          ], key=("pattern", "routePartitionName"), key_extra=PATTERN_KEY, list_criteria="pattern",
          about="Calling Party Transformation Patterns."),

    Sheet("Called Party Xforms", "CalledPartyTransformationPattern",
          "calledPartyTransformationPattern", [
              F("Pattern", "pattern", req=True, key=True),
              F("Partition", "routePartitionName", key=True),
              F("Description", "description"),
              F("Called Party Mask", "calledPartyTransformationMask"),
              F("Prefix Digits", "calledPartyPrefixDigits"),
              F("Discard Digits", "digitDiscardInstructionName"),
          ], key=("pattern", "routePartitionName"), key_extra=PATTERN_KEY, list_criteria="pattern",
          about="Called Party Transformation Patterns."),

    Sheet("Voicemail Pilots", "VoiceMailPilot", "voiceMailPilot", [
        F("Pilot Number", "dirn", req=True, key=True, hint="Unity Connection pilot DN"),
        F("CSS", "cssName", key=True),
        F("Description", "description"),
        F("Default", "isDefault", kind=Y, default="No"),
    ], key=("dirn", "cssName"), list_criteria="dirn"),

    Sheet("Voicemail Profiles", "VoiceMailProfile", "voiceMailProfile", [
        F("Name", "name", req=True, key=True, hint="e.g. VMP_CUC"),
        F("Description", "description"),
        F("Pilot Number", "voiceMailPilot.dirn", req=True),
        F("Pilot CSS", "voiceMailPilot.cssName"),
        F("Mailbox Mask", "voiceMailboxMask"),
        F("Default", "isDefault", kind=Y, default="No"),
    ]),

    Sheet("Call Pickup Groups", "CallPickupGroup", "callPickupGroup", [
        F("Name", "name", req=True, key=True, hint="e.g. CPG_Sales"),
        F("Pickup Number", "pattern", req=True),
        F("Partition", "routePartitionName"),
        F("Description", "description"),
        F("Notification", "pickupNotification", default="No Alert", choices="enum"),
        F("Notification Timer", "pickupNotificationTimer", kind=I),
    ]),

    Sheet("Conference Now", "ConferenceNow", "conferenceNow", [
        F("Number", "conferenceNowNumber", req=True, key=True),
        F("Partition", "routePartitionName", key=True),
        F("Description", "description"),
        F("Max Wait For Host (min)", "maxWaitTimeForHost", kind=I, default="15"),
    ], key=("conferenceNowNumber", "routePartitionName"), min_version="11.0",
       list_criteria="conferenceNowNumber", about="Conference Now (CUCM 11.0 and later)."),

    Sheet("Universal Line Templates", "UniversalLineTemplate", "universalLineTemplate", [
        F("Name", "name", req=True, key=True, hint="e.g. ULT_HQ"),
        F("Line Description", "lineDescription", default="#FirstName# #LastName#"),
        F("Partition", "routePartition"),
        F("Line CSS", "callingSearchSpace"),
        F("Voicemail Profile", "voiceMailProfile"),
        F("Alerting Name", "alertingName", default="#FirstName# #LastName#"),
        F("Presence Group", "blfPresenceGroup", default="Standard Presence group"),
        F("Call Pickup Group", "callPickupGroup"),
        F("Forward All CSS", "primaryCssForwardingAllCalls"),
        F("Forward Busy/No Answer Destination", None,
          build=copy_to("busyIntCallsDestination", "busyExtCallsDestination",
                        "noAnsIntCallsDestination", "noAnsExtCallsDestination"),
          hint="e.g. voicemail pilot"),
        F("Forward Busy/No Answer CSS", None,
          build=copy_to("busyIntCallsCss", "busyExtCallsCss", "noAnsIntCallsCss",
                        "noAnsExtCallsCss")),
        F("No Answer Ring Duration", "noAnswerRingDuration", kind=I),
    ], const={"partyEntranceTone": "Default", "autoAnswer": "Auto Answer Off"}, min_version="10.0",
       about="Universal Line Templates for self-provisioning / LDAP sync (CUCM 10.0+)."),

    Sheet("Universal Device Templates", "UniversalDeviceTemplate", "universalDeviceTemplate", [
        F("Name", "name", req=True, key=True, hint="e.g. UDT_HQ"),
        F("Device Description", "deviceDescription", default="#FN# #LN# #PRODUCTMODEL#"),
        F("Device Pool", "devicePool", req=True, default="Default"),
        F("Security Profile", "deviceSecurityProfile", req=True,
          default="Universal Device Template - Model-independent Security Profile", width=30),
        F("SIP Profile", "sipProfile", req=True, default="Standard SIP Profile"),
        F("Phone Button Template", "phoneButtonTemplate", req=True,
          default="Universal Device Template Button Layout", width=30),
        F("Device CSS", "callingSearchSpace"),
        F("Common Phone Profile", "commonPhoneProfile", default="Standard Common Phone Profile"),
        F("Softkey Template", "softkeyTemplate", default="Standard User"),
        F("Location", "location", default="Hub_None"),
        F("Media Resource List", "mediaResourceGroupList"),
        F("Presence Group", "blfPresenceGroup", default="Standard Presence group"),
        F("Line Label", None, build=udt_line("label", "lineLabel"), default="#FN# #LN# #EXT#"),
        F("Line Display", None, build=udt_line("display", "displayCallerId"),
          default="#FN# #LN#"),
        F("External Phone Mask", None, build=udt_line("e164Mask", "externalPhoneNumber"),
          hint="e.g. 2412XXXX"),
    ], min_version="10.0", about="Universal Device Templates (CUCM 10.0+)."),

    Sheet("Directory Numbers", "Line", "line", [
        F("Directory Number", "pattern", req=True, key=True, hint="e.g. 1001"),
        F("Partition", "routePartitionName", key=True),
        F("Description", "description"),
        F("Alerting Name", "alertingName"),
        F("ASCII Alerting Name", "asciiAlertingName"),
        F("Line CSS", "shareLineAppearanceCssName"),
        F("Voicemail Profile", "voiceMailProfileName"),
        F("Forward CSS", None, build=line_forward_css, hint="CSS for all call-forward types"),
        F("Forward Busy to VM", None, kind=Y,
          build=line_forward_vm("callForwardBusy", "callForwardBusyInt")),
        F("Forward No Answer to VM", None, kind=Y,
          build=line_forward_vm("callForwardNoAnswer", "callForwardNoAnswerInt")),
        F("Forward Unregistered to VM", None, kind=Y,
          build=line_forward_vm("callForwardNotRegistered", "callForwardNotRegisteredInt")),
        F("No Answer Ring Duration", None, kind=I, build=line_noanswer_duration),
        F("Call Pickup Group", "callPickupGroupName"),
        F("Presence Group", "presenceGroupName"),
        F("Auto Answer", "autoAnswer", choices="enum"),
    ], key=("pattern", "routePartitionName"), const={"usage": "Device"}, list_criteria="pattern"),

    Sheet("End Users", "User", "user", [
        F("User ID", "userid", req=True, key=True),
        F("First Name", "firstName"),
        F("Last Name", "lastName", req=True),
        F("Display Name", "displayName"),
        F("Email", "mailid"),
        F("Department", "department"),
        F("Telephone Number", "telephoneNumber"),
        F("Password", "password", hint="local users only"),
        F("PIN", "pin"),
        F("Access Control Groups", None, build=user_groups, width=34,
          hint="e.g. Standard CCM End Users;Standard CTI Enabled"),
        F("Home Cluster", "homeCluster", kind=Y, default="Yes"),
        F("IM and Presence", "imAndPresenceEnable", kind=Y),
        F("Service Profile", "serviceProfile"),
        F("Enable Mobility", "enableMobility", kind=Y),
        F("Presence Group", "presenceGroupName", default="Standard Presence group"),
        F("Controlled Devices", None, build=user_devices, hint="applied after Phones", width=30,
          post=True),
        F("Primary Extension", None, build=user_primary, hint="1001/PT_Internal - after Phones",
          post=True),
    ], key=("userid",), deferred=("associatedDevices", "primaryExtension"), list_criteria="userid",
       about="Local end users (LDAP-synced users cannot be added here). Devices and primary "
             "extension are applied after the Phones sheet."),

    Sheet("Phones", "Phone", "phone", [
        F("Device Name", "name", req=True, key=True, hint="SEPxxxxxxxxxxxx / CSFuser / BOTuser"),
        F("Description", "description"),
        F("Product", "product", req=True, hint="e.g. Cisco 8845 / Cisco Unified Client Services Framework",
          width=26),
        F("Protocol", "protocol", default="SIP", choices=["SIP", "SCCP"]),
        F("Device Pool", "devicePoolName", req=True),
        F("Device CSS", "callingSearchSpaceName"),
        F("Location", "locationName", default="Hub_None"),
        F("Media Resource List", "mediaResourceListName"),
        F("Phone Button Template", "phoneTemplateName", req=True, hint="e.g. Standard 8845 SIP"),
        F("Softkey Template", "softkeyTemplateName"),
        F("Common Phone Profile", "commonPhoneConfigName", default="Standard Common Phone Profile"),
        F("Security Profile", "securityProfileName", width=30,
          hint="e.g. Cisco 8845 - Standard SIP Non-Secure Profile"),
        F("SIP Profile", "sipProfileName", default="Standard SIP Profile"),
        F("Owner User ID", "ownerUserName"),
        F("Lines", None, build=phone_lines, hint="DN/Partition ; separated, e.g. 1001/PT_Internal",
          width=30),
        F("Line 1 Display", None, build=first_line("display")),
        F("Line 1 Label", None, build=first_line("label")),
        F("Line 1 External Mask", None, build=first_line("e164Mask")),
        F("Speed Dials", None, build=speed_dials, hint="number:label ; separated"),
        F("Built In Bridge", "builtInBridgeStatus", choices="enum"),
        F("Extension Mobility", "enableExtensionMobility", kind=Y),
    ], const={"class": "Phone", "protocolSide": "User"}, finish=phone_finish),

    Sheet("Line Groups", "LineGroup", "lineGroup", [
        F("Name", "name", req=True, key=True, hint="e.g. LG_Reception"),
        F("Distribution Algorithm", "distributionAlgorithm", default="Top Down", choices="enum"),
        F("RNA Reversion Timeout", "rnaReversionTimeOut", kind=I, default="10"),
        F("No Answer", "huntAlgorithmNoAnswer", choices="enum",
          default="Try next member; then, try next group in Hunt List"),
        F("Busy", "huntAlgorithmBusy", choices="enum",
          default="Try next member; then, try next group in Hunt List"),
        F("Not Available", "huntAlgorithmNotAvailable", choices="enum",
          default="Try next member; then, try next group in Hunt List"),
        F("Members (in order)", None, build=line_group_members,
          hint="DN/Partition ; separated", width=34),
        F("Auto Logout On No Answer", "autoLogOffHunt", kind=Y),
    ]),

    Sheet("Hunt Lists", "HuntList", "huntList", [
        F("Name", "name", req=True, key=True, hint="e.g. HL_Reception"),
        F("Description", "description"),
        F("CallManager Group", "callManagerGroupName", req=True, default="Default"),
        F("Enabled", "routeListEnabled", kind=Y, default="Yes"),
        F("For Voice Mail Usage", "voiceMailUsage", kind=Y),
        F("Line Groups (in order)", None, req=True,
          build=members("members", "member", "lineGroupName", "selectionOrder", 1), width=34),
    ]),

    Sheet("Hunt Pilots", "HuntPilot", "huntPilot", [
        F("Pattern", "pattern", req=True, key=True),
        F("Partition", "routePartitionName", key=True),
        F("Description", "description"),
        F("Hunt List", "huntListName", req=True),
        F("Alerting Name", "alertingName"),
        F("Block Pattern", "blockEnable", kind=Y, default="No"),
        F("Provide Outside Dial Tone", "provideOutsideDialtone", kind=Y, default="No"),
        F("Calling Party Mask", "callingPartyTransformationMask"),
        F("Max Hunt Timer (s)", "maxHuntduration", kind=I),
        F("Forward No Answer To", None, build=hunt_forward("forwardHuntNoAnswer", "destination")),
        F("Forward No Answer CSS", None,
          build=hunt_forward("forwardHuntNoAnswer", "callingSearchSpaceName")),
        F("Forward Busy To", None, build=hunt_forward("forwardHuntBusy", "destination")),
        F("Forward Busy CSS", None, build=hunt_forward("forwardHuntBusy", "callingSearchSpaceName")),
    ], key=("pattern", "routePartitionName"), const={"useCallingPartyPhoneMask": "Default"},
       list_criteria="pattern"),
]

SHEET_BY_NAME = {s.name: s for s in SHEETS}

# Add/Update order. ("post", sheet) = the sheet's deferred fields (applied with updateXxx).
DEPLOY_PLAN = [("main", s.name) for s in SHEETS if s.name not in ("Phones", "Line Groups",
                                                                    "Hunt Lists", "Hunt Pilots")]
DEPLOY_PLAN += [("main", "Phones"), ("post", "End Users"), ("main", "Line Groups"),
                ("main", "Hunt Lists"), ("main", "Hunt Pilots")]
