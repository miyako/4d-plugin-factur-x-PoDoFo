# Same as the stock x64-windows-static triplet, but release-only. vcpkg
# otherwise builds PoDoFo and its whole dependency graph twice, which doubled
# the CI configure step to 24 minutes. Both workflows build Release only.
set(VCPKG_TARGET_ARCHITECTURE x64)
set(VCPKG_CRT_LINKAGE static)
set(VCPKG_LIBRARY_LINKAGE static)
set(VCPKG_BUILD_TYPE release)
