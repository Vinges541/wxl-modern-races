/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Only appearance DBC names are redirected; the native reader owns all bytes. */
#define WXL_EXTENSION
#include "wxl/PluginApi.h"

#ifdef WXL_DRUID_FORMS
#define PLUGIN_NAME "wxl-druid-forms"
#define LOG_CHANNEL "druid-forms"
#define TABLE_ONE "CreatureDisplayInfo.dbc"
#define TABLE_TWO "CreatureModelData.dbc"
#define TABLE_ROOT "WXL\\DruidForms\\DBFilesClient\\"
#else
#define PLUGIN_NAME "wxl-modern-races"
#define LOG_CHANNEL "modern-races"
#define TABLE_ONE "CharSections.dbc"
#define TABLE_TWO "CreatureDisplayInfoExtra.dbc"
#define TABLE_ROOT "WXL\\ModernRaces\\DBFilesClient\\"
#endif

static const WXL_Api* services;
static int registered;
typedef int (__stdcall* FileOpenFn)(void*, const char*, uint32_t, void**);
static FileOpenFn original_open;
static const WXL_PluginInfo info = {
    sizeof(WXL_PluginInfo), WXL_API_VERSION, PLUGIN_NAME, 1, WXL_CLIENT_BUILD
};

static unsigned char fold(unsigned char c)
{
    if (c == '/') return '\\';
    return c >= 'A' && c <= 'Z' ? (unsigned char)(c + 'a' - 'A') : c;
}

static int same_name(const char* a, const char* b)
{
    if (!a) return 0;
    while (*b) {
        if (fold((unsigned char)*a) != fold((unsigned char)*b)) return 0;
        ++a;
        ++b;
    }
    return *a == 0;
}

static const char* redirect(void* archive, const char* name)
{
    const char* replacement;
    /* An explicit archive handle must retain its original lookup semantics. */
    if (archive) return name;
    if (same_name(name, "DBFilesClient\\" TABLE_ONE))
        replacement = TABLE_ROOT TABLE_ONE;
    else if (same_name(name, "DBFilesClient\\" TABLE_TWO))
        replacement = TABLE_ROOT TABLE_TWO;
    else return name;
    if (services && services->Log)
        services->Log(WXL_LOG_INFO, LOG_CHANNEL, "appearance redirect: %s", replacement);
    return replacement;
}

static int __stdcall open_file(void* archive, const char* name, uint32_t flags, void** out)
{
    return original_open(archive, redirect(archive, name), flags, out);
}

const WXL_PluginInfo* __cdecl WXL_Query(void) { return &info; }

int __cdecl WXL_Load(const WXL_Api* api)
{
    if (!api || api->structSize < offsetof(WXL_Api, HookAttachByName) + sizeof(api->HookAttachByName)
        || api->apiVersion != WXL_API_VERSION || !api->HookAttachByName) return 0;
    if (registered) return 1;
    services = api;
    /* WXL_Load is synchronous before EngineInit. The storage service's own
       detours are installed on a deferred thread in the pinned core; using its
       named chain here guarantees the redirects are armed before DBCs. Equal
       priority permits either registration order without replacing a live head.
       Do not use Io.FileOpenAlt: its pinned address is an archive-open wrapper,
       not a second file-open function (verified against build 12340). */
    if (!api->HookAttachByName("Io.FileOpen", (void*)&open_file, (void**)&original_open,
                               WXL_HOOK_DEFAULT_PRIORITY)) return 0;
    registered = 1;
    if (services->Log)
        services->Log(WXL_LOG_INFO, LOG_CHANNEL, "locale-independent appearance redirects ready");
    return 1;
}
