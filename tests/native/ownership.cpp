#include "4DPluginAPI.h"
#include "PrivateTypes.h"
#include "EntryPoints.h"

#ifndef FACTURX_SOURCE
#define FACTURX_SOURCE "../../facturx/facturx-4dplugin.cpp"
#endif
#include FACTURX_SOURCE

#include <codecvt>
#include <cstdlib>
#include <iostream>
#include <locale>
#include <unordered_map>

namespace host {

struct Ref {
    int owners = 1;
    bool collection = false;
    std::map<std::u16string, PA_Variable> properties;
    std::vector<PA_Variable> elements;
};

std::unordered_map<PA_Unichar*, size_t> strings;
std::unordered_map<PA_Handle, size_t> handles;
std::set<Ref*> refs;
std::string failure;
PA_Unistring poison {};
bool allocated_empty = true;
size_t clears = 0;

void require(bool ok, char const* message)
{
    if (!ok) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

PA_Variable undefined()
{
    PA_Variable v {};
    v.fType = eVK_Undefined;
    return v;
}

std::u16string text(PA_Unistring const& u)
{
    if (!u.fString) {
        require(u.fLength == 0, "null string length");
        return {};
    }
    auto it = strings.find(static_cast<PA_Unichar*>(u.fString));
    require(it != strings.end(), "read non-owned/freed string");
    require(u.fLength >= 0 && static_cast<size_t>(u.fLength) < it->second,
            "string length/capacity");
    require(u.fString[u.fLength] == 0, "string terminator");
    return {reinterpret_cast<char16_t*>(u.fString), static_cast<size_t>(u.fLength)};
}

PA_Unistring create(std::u16string const& s)
{
    PA_Unistring u {};
    u.fLength = static_cast<PA_long32>(s.size());
    if (!s.empty() || allocated_empty) {
        u.fString = new PA_Unichar[s.size() + 1];
        strings.emplace(static_cast<PA_Unichar*>(u.fString), s.size() + 1);
        std::memcpy(u.fString, s.c_str(), (s.size() + 1) * sizeof(PA_Unichar));
    }
    return u;
}

void dispose(PA_Unistring u)
{
    if (u.fString) {
        require(u.fString != poison.fString, "failed getter output was cleared");
        require(strings.erase(static_cast<PA_Unichar*>(u.fString)) == 1,
                "double/borrowed string disposal");
        delete[] u.fString;
    }
}

Ref* ref(void* p)
{
    auto* r = static_cast<Ref*>(p);
    require(refs.count(r) == 1, "dead object/collection reference");
    return r;
}

void clear(PA_Variable& v);

void release(void* p)
{
    if (!p) return;
    Ref* r = ref(p);
    if (--r->owners == 0) {
        for (auto& entry : r->properties) clear(entry.second);
        for (auto& item : r->elements) clear(item);
        refs.erase(r);
        delete r;
    }
}

PA_Variable copy(PA_Variable const& v)
{
    PA_Variable out = v;
    if (v.fType == eVK_Unistring) out.uValue.fString = create(text(v.uValue.fString));
    if (v.fType == eVK_Object && v.uValue.fObject) ++ref(v.uValue.fObject)->owners;
    if (v.fType == eVK_Collection && v.uValue.fCollection) ++ref(v.uValue.fCollection)->owners;
    return out;
}

void clear(PA_Variable& v)
{
    ++clears;
    require(v.fType != 0, "raw-kind-0 sentinel was cleared");
    switch (v.fType) {
    case eVK_Unistring: dispose(v.uValue.fString); break;
    case eVK_Object: release(v.uValue.fObject); break;
    case eVK_Collection: release(v.uValue.fCollection); break;
    case eVK_ArrayUnicode: {
        auto* data = reinterpret_cast<PA_Unistring*>(*v.uValue.fArray.fData);
        for (PA_long32 i = 0; i <= v.uValue.fArray.fNbElements; ++i) dispose(data[i]);
        PA_DisposeHandle(v.uValue.fArray.fData);
        break;
    }
    case eVK_Undefined: case eVK_Null: case eVK_Boolean: case eVK_Longint: break;
    default: require(false, "unexpected variable cleanup");
    }
    v = undefined();
}

PA_Variable new_ref(bool collection)
{
    auto* r = new Ref;
    r->collection = collection;
    refs.insert(r);
    PA_Variable v = undefined();
    if (collection) PA_SetCollectionVariable(&v, reinterpret_cast<PA_CollectionRef>(r));
    else PA_SetObjectVariable(&v, reinterpret_cast<PA_ObjectRef>(r));
    return v;
}

void callback(short selector, EngineBlock* eb)
{
    switch (selector) {
    case EX_CREATE_UNISTRING:
        eb->fUniString1 = create(std::u16string(reinterpret_cast<char16_t*>(eb->fHandle)));
        break;
    case EX_DISPOSE_UNISTRING: dispose(eb->fUniString1); break;
    case EX_SET_UNISTRING: {
        std::u16string s(reinterpret_cast<char16_t*>(eb->fHandle));
        dispose(eb->fUniString1);
        eb->fUniString1 = create(s);
        break;
    }
    case EX_CONVERT_CHARSET_TO_CHARSET: {
        std::wstring_convert<std::codecvt_utf8_utf16<char16_t>, char16_t> codec;
        std::string bytes;
        if (eb->fParam2 == eVTC_UTF_8 && eb->fParam4 == eVTC_UTF_16) {
            auto* p = static_cast<char*>(eb->fPtr1);
            std::u16string s = codec.from_bytes(p, p + eb->fParam1);
            bytes.assign(reinterpret_cast<char const*>(s.data()), s.size() * sizeof(PA_Unichar));
        } else {
            require(eb->fParam2 == eVTC_UTF_16 && eb->fParam4 == eVTC_UTF_8,
                    "charset direction");
            require(eb->fParam1 % sizeof(PA_Unichar) == 0, "UTF16 byte input length");
            auto* p = static_cast<char16_t*>(eb->fPtr1);
            bytes = codec.to_bytes(p, p + eb->fParam1 / sizeof(PA_Unichar));
        }
        require(bytes.size() <= static_cast<size_t>(eb->fParam3), "charset byte capacity");
        std::memcpy(eb->fPtr2, bytes.data(), bytes.size());
        eb->fParam3 = bytes.size(); // SDK returns bytes, excluding any terminator.
        break;
    }
    case EX_HANDLE_MANAGER: {
        PA_Handle h = eb->fParam1 == 1 ? nullptr : eb->fHandle;
        sLONG_PTR size = (eb->fParam1 == 1 || eb->fParam1 == 3) ? eb->fParam2 : 0;
        switch (eb->fParam1) {
        case 1:
            h = new char*;
            *h = static_cast<char*>(std::calloc(1, std::max<sLONG_PTR>(1, size)));
            eb->fHandle = h;
            handles.emplace(h, size);
            break;
        case 2:
            require(handles.erase(h) == 1, "handle disposal");
            std::free(*h);
            delete h;
            break;
        case 3:
            require(handles.count(h) == 1, "resize live handle");
            *h = static_cast<char*>(std::realloc(*h, size));
            require(*h != nullptr, "host allocation");
            handles[h] = size;
            break;
        case 4: eb->fParam2 = handles.at(h); break;
        case 5: eb->fParam3 = reinterpret_cast<sLONG_PTR>(*h); break;
        case 6: break;
        default: require(false, "handle operation");
        }
        break;
    }
    case EX_GET_INFORMATION: eb->fParam2 = 0x2100; break;
    case EX_EXECUTE_COMMAND_BY_ID: {
        require(eb->fParam1 == 1471 || eb->fParam1 == 1472, "only new object/collection command");
        *static_cast<PA_Variable*>(eb->fPtr2) = new_ref(eb->fParam1 == 1472);
        break;
    }
    case EX_CLEAR_VARIABLE: clear(*static_cast<PA_Variable*>(eb->fPtr1)); break;
    case EX_VARIABLE_TO_STRING: {
        auto* v = reinterpret_cast<PA_Variable*>(eb->fHandle);
        require(v->fType == eVK_Unistring,
                "failed property output became raw-kind-0 string sentinel");
        text(v->uValue.fString);
        eb->fUniString1 = v->uValue.fString;
        break;
    }
    case EX_GET_OBJ_VALUE: {
        Ref* r = ref(eb->fPtr1);
        auto* out = static_cast<PA_Variable*>(eb->fPtr2);
        bool collection_item = eb->fShort == eVK_Collection && eb->fLongint >= 0;
        if ((!collection_item && eb->fShort == eVK_Object && failure.find("property") == 0) ||
            (collection_item && failure.find("collection") == 0)) {
            // A failed output has no ownership contract. Poison it with a borrowed
            // descriptor to detect adoption without relying on stack randomness.
            if (failure.find("untouched") == std::string::npos) {
                *out = undefined();
                PA_SetStringVariable(out, &poison);
            }
            eb->fError = eER_CallNotImplemented;
            break;
        }
        if (collection_item) {
            require(static_cast<size_t>(eb->fLongint) < r->elements.size(), "collection index");
            *out = copy(r->elements[eb->fLongint]);
        } else if (eb->fShort == eVK_Collection) {
            *out = undefined();
            PA_SetLongintVariable(out, static_cast<PA_long32>(r->elements.size()));
        } else {
            auto it = r->properties.find(text(eb->fUniString1));
            *out = it == r->properties.end() ? undefined() : copy(it->second);
        }
        break;
    }
    case EX_SET_OBJ_VALUE: {
        Ref* r = ref(eb->fPtr1);
        PA_Variable v = copy(*static_cast<PA_Variable*>(eb->fPtr2));
        if (eb->fShort == eVK_Collection) {
            while (r->elements.size() <= static_cast<size_t>(eb->fLongint))
                r->elements.push_back(undefined());
            clear(r->elements[eb->fLongint]);
            r->elements[eb->fLongint] = v;
        } else {
            auto key = text(eb->fUniString1);
            auto it = r->properties.find(key);
            if (it != r->properties.end()) clear(it->second);
            r->properties[key] = v;
        }
        break;
    }
    default:
        std::cerr << "unexpected engine selector " << selector << '\n';
        std::exit(1);
    }
}

void failed_getter(std::string const& which)
{
    PA_ObjectRef obj = PA_CreateObject();
    PA_CollectionRef col = PA_CreateCollection();
    PA_Variable item = undefined();
    PA_SetObjectVariable(&item, obj);
    PA_SetCollectionElement(col, 0, item);
    PA_ClearVariable(&item);
    failure = which;
    bool caught = false;
    size_t before = clears;
    try {
        if (which.find("property") == 0) {
            std::string out;
            object_get_text(reinterpret_cast<PA_ObjectRef>(ref(col)->elements[0].uValue.fObject),
                            "path", out, "xmlInfo");
        } else {
            parse_attachments(col, XmlInfo {});
        }
    } catch (FxError const& e) {
        caught = e.code() == FX_BACKEND_ERROR &&
            e.message().find("-1") != std::string::npos;
    }
    require(caught, "getter failure must report backend error, not absence/type mismatch");
    require(clears == before, "failed output must never be adopted or cleared");
    failure.clear();
    PA_DisposeCollection(col);
}

void success()
{
    PA_ObjectRef obj = PA_CreateObject();
    std::vector<std::pair<std::string, std::u16string>> fixtures = {
        {"", u""}, {"ASCII", u"ASCII"}, {"\xc3\xa9\xe6\x97\xa5", u"\u00e9\u65e5"},
        {"a\xf0\x9f\x98\x80z", u"a\U0001f600z"}};
    for (bool empty : {false, true}) {
        allocated_empty = empty;
        for (auto const& fixture : fixtures) {
            std::string const& s = fixture.first;
            object_set_text(obj, "text", s);
            std::string out = "unchanged";
            require(object_get_text(obj, "text", out, "fixture") && out == s,
                    "exact Unicode property roundtrip");
            auto w = utf8_to_utf16(s);
            auto const& expected = fixture.second;
            require(w.size() == expected.size() + 1 && w.back() == 0,
                    "UTF16 code units and terminator");
            require(std::equal(expected.begin(), expected.end(), w.begin()), "UTF16 exact content");
        }
    }
    allocated_empty = true;
    object_set_bool(obj, "bool", true);
    require(object_get_bool(obj, "bool", false, "fixture"), "boolean getter");
    std::string out = "unchanged";
    require(!object_get_text(obj, "absent", out, "fixture") && out == "unchanged", "missing property");
    try {
        object_get_text(obj, "bool", out, "fixture");
        require(false, "mismatch must throw");
    } catch (FxError const& e) { require(e.code() == FX_PROPERTY_WRONG_TYPE, "mismatch code"); }
    PA_DisposeObject(obj);

    PA_CollectionRef mismatch = PA_CreateCollection();
    {
        UStr input("not an object");
        PA_Variable v = undefined();
        PA_SetStringVariable(&v, input.get());
        PA_SetCollectionElement(mismatch, 0, v);
        // v only aliases input; the synchronous setter copied its contents.
    }
    try {
        parse_attachments(mismatch, XmlInfo {});
        require(false, "attachment mismatch must throw");
    } catch (FxError const& e) { require(e.code() == FX_ATTACHMENT_NOT_OBJECT, "attachment mismatch code"); }
    PA_DisposeCollection(mismatch);

    Result r;
    r.message = "message \xf0\x9f\x98\x80";
    r.warnings = {"ASCII", "\xe6\x97\xa5", "\xf0\x9f\x98\x80", ""};
    PA_ObjectRef status = make_status(r);
    PA_ObjectRef returned = nullptr;
    PluginBlock params {};
    params.fResult = &returned;
    PA_ReturnObject(&params, status);
    require(returned == status, "owning return handoff");
    require(object_get_text(returned, "errorMessage", out, "status") && out == r.message,
            "status survives setter input cleanup");
    {
        PAVar warnings(object_property(returned, "warnings"));
        PA_CollectionRef col = PA_GetCollectionVariable(warnings.get());
        for (size_t i = 0; i < r.warnings.size(); ++i) {
            PAVar v(PA_GetCollectionElement(col, i));
            require(utf16_to_utf8(PA_GetStringVariable(v.get())) == r.warnings[i],
                    "independently owned warning");
        }
    }
    PA_DisposeObject(returned);

    {
        UStr empty("");
        void* arguments[] = {empty.get(), nullptr, empty.get(), nullptr, nullptr};
        PA_ObjectRef command_result = nullptr;
        FourDPackex(1, arguments, nullptr, &command_result);
        PAVar code(object_property(command_result, "errorCode"));
        require(PA_GetLongintVariable(code.get()) == FX_IN_PATH_EMPTY,
                "exported dispatcher returns error status");
        PA_DisposeObject(command_result);
    }

    PA_Variable arr = PA_CreateVariable(eVK_ArrayUnicode);
    PA_ResizeArray(&arr, 2);
    for (PA_long32 i = 0; i <= 2; ++i) {
        UStr input("array");
        PA_Unistring independent = PA_CreateUnistring(PA_GetUnistring(input.get()));
        PA_SetStringInArray(arr, i, &independent);
    }
    PA_Unistring borrowed = PA_GetStringInArray(arr, 1);
    PA_Unistring independent = PA_CreateUnistring(borrowed.fString);
    PA_SetStringInArray(arr, 1, &independent);
    require(text(PA_GetStringInArray(arr, 1)) == u"array", "borrowed copy before replacement");
    for (PA_long32 bad : {-1, 3}) {
        UStr input("rejected");
        PA_SetStringInArray(arr, bad, input.get());
        require(text(*input.get()) == u"rejected", "rejection retains caller owner");
    }
    PA_Variable wrong = undefined();
    { UStr input("wrong"); PA_SetStringInArray(wrong, 0, input.get()); }
    {
        UStr input("no data");
        PA_Variable no_data = undefined();
        no_data.fType = eVK_ArrayUnicode;
        no_data.uValue.fArray.fNbElements = 1;
        no_data.uValue.fArray.fData = nullptr;
        PA_SetStringInArray(no_data, 0, input.get());
        require(text(*input.get()) == u"no data", "null data retains caller owner");
        PA_SetStringInArray(arr, 1, nullptr);
        require(text(PA_GetStringInArray(arr, 1)) == u"array", "null input preserves element");
    }
    PA_ResizeArray(&arr, 0);
    PA_ClearVariable(&arr);
}

} // namespace host

int main(int argc, char** argv)
{
    host::require(argc == 2, "test name required");
    gCall4D = host::callback;
    host::poison = host::create(u"borrowed failed output");
    std::string test = argv[1];
    if (test == "success") host::success();
    else if (test == "default-variable") {
        PAVar empty;
        host::require(empty.kind() == eVK_Undefined, "default owner must be Undefined, not raw kind 0");
    } else host::failed_getter(test);
    PA_Unistring poison = host::poison;
    host::poison = {};
    host::dispose(poison);
    host::require(host::strings.empty(), "string allocation balance");
    host::require(host::handles.empty(), "handle allocation balance");
    host::require(host::refs.empty(), "object/collection reference balance");
    std::cout << "PASS: " << test << '\n';
}
