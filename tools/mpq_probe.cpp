#include "StormLib.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <string>

namespace
{
  std::string Lower(const char* value)
  {
    std::string result(value);
    std::transform(result.begin(), result.end(), result.begin(),
      [](unsigned char character) { return static_cast<char>(std::tolower(character)); });
    return result;
  }
}

int main(int argc, char** argv)
{
  if (argc < 3)
  {
    std::fprintf(stderr, "usage: mpq-probe <internal-path|--find:substring> <archive>...\n");
    return 2;
  }

  bool found = false;
  const std::string request = argv[1];
  const bool list_mode = request.rfind("--find:", 0) == 0;
  const std::string needle = list_mode ? Lower(request.c_str() + 7) : std::string();
  for (int i = 2; i < argc; ++i)
  {
    HANDLE archive = nullptr;
    if (!SFileOpenArchive(argv[i], 0, MPQ_OPEN_READ_ONLY, &archive))
    {
      std::fprintf(stderr, "cannot open: %s\n", argv[i]);
      continue;
    }
    if (list_mode)
    {
      SFILE_FIND_DATA data{};
      HANDLE search = SFileFindFirstFile(archive, "*", &data, nullptr);
      if (search)
      {
        do
        {
          if (Lower(data.cFileName).find(needle) != std::string::npos)
          {
            std::printf("FOUND\t%u\t%s\t%s\n", static_cast<unsigned>(data.dwFileSize),
              argv[i], data.cFileName);
            found = true;
          }
        }
        while (SFileFindNextFile(search, &data));
        SFileFindClose(search);
      }
      SFileCloseArchive(archive);
      continue;
    }

    HANDLE file = nullptr;
    if (SFileOpenFileEx(archive, request.c_str(), SFILE_OPEN_FROM_MPQ, &file))
    {
      const DWORD size = SFileGetFileSize(file, nullptr);
      std::printf("FOUND\t%u\t%s\n", static_cast<unsigned>(size), argv[i]);
      SFileCloseFile(file);
      found = true;
    }
    SFileCloseArchive(archive);
  }
  return found ? 0 : 1;
}
