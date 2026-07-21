CXX ?= g++
CPPFLAGS ?=
CXXFLAGS_COMMON := -std=c++17 -Wall -Wextra -Wpedantic
CXXFLAGS_RELEASE := -O3 -DNDEBUG -march=native
CXXFLAGS_DEBUG := -O0 -g3
LDLIBS ?=

TARGET := obj/uatu_solver
PROFILE_TARGET := obj/uatu_solver_profile
DEBUG_TARGET := obj/uatu_solver_debug
SOURCES := solver.cpp main.cpp
HEADERS := solver.h

.PHONY: all release profile debug clean run run-profile run-debug

all: release
release: $(TARGET)
profile: $(PROFILE_TARGET)
debug: $(DEBUG_TARGET)

obj:
	mkdir -p $@

$(TARGET): $(SOURCES) $(HEADERS) | obj
	$(CXX) $(CPPFLAGS) $(CXXFLAGS_COMMON) $(CXXFLAGS_RELEASE) -DUATU_PROFILE_BCP=0 $(SOURCES) $(LDLIBS) -o $@

$(PROFILE_TARGET): $(SOURCES) $(HEADERS) | obj
	$(CXX) $(CPPFLAGS) $(CXXFLAGS_COMMON) $(CXXFLAGS_RELEASE) -DUATU_PROFILE_BCP=1 $(SOURCES) $(LDLIBS) -o $@

$(DEBUG_TARGET): $(SOURCES) $(HEADERS) | obj
	$(CXX) $(CPPFLAGS) $(CXXFLAGS_COMMON) $(CXXFLAGS_DEBUG) -DUATU_PROFILE_BCP=1 $(SOURCES) $(LDLIBS) -o $@

CNF ?= ../../benchmark/sample/cnf/benchmark1.cnf
TIMEOUT ?= 1000

run: $(TARGET)
	@UATU_TIMEOUT_SEC=$(TIMEOUT) $(TARGET) $(CNF); rc=$$?; \
	if [ $$rc -ne 0 ] && [ $$rc -ne 10 ] && [ $$rc -ne 20 ]; then exit $$rc; fi

run-profile: $(PROFILE_TARGET)
	@UATU_TIMEOUT_SEC=$(TIMEOUT) $(PROFILE_TARGET) $(CNF); rc=$$?; \
	if [ $$rc -ne 0 ] && [ $$rc -ne 10 ] && [ $$rc -ne 20 ]; then exit $$rc; fi

run-debug: $(DEBUG_TARGET)
	@UATU_TIMEOUT_SEC=$(TIMEOUT) $(DEBUG_TARGET) $(CNF); rc=$$?; \
	if [ $$rc -ne 0 ] && [ $$rc -ne 10 ] && [ $$rc -ne 20 ]; then exit $$rc; fi

clean:
	rm -rf obj
