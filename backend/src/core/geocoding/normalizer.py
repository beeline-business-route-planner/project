import re


class RussianAddressNormalizer:
    @staticmethod
    def queries(address: str) -> tuple[str, ...]:
        normalized_address = " ".join(address.split())
        search_address = RussianAddressNormalizer.normalize(normalized_address)
        simplified_address = re.sub(
            r"^(?:Московская область,\s*)?(?:г\.)?([^,]+),\s*"
            r"(?:посёлок|поселок|пгт)\s+[^,]+,\s*",
            r"\1, ",
            search_address,
        )
        return tuple(dict.fromkeys((search_address, simplified_address, normalized_address)))

    @staticmethod
    def normalize(address: str) -> str:
        value = address
        value = re.sub(r"^(?:г\.\s*)?(?:Город\s+)?Москва,?\s*", "Москва, ", value)
        value = re.sub(r"^МО,\s*г\.\s*", "Московская область, ", value)
        value = value.replace("обл.Московская область", "Московская область")
        value = value.replace("пгт.", "посёлок ")

        remote_street = re.match(
            r"^(Московская область,\s*)?(Кашира|Ступино)\s+(.+?)\s+ул\.\s+д\.\s+(.+)$",
            value,
        )
        if remote_street is not None:
            region = remote_street.group(1) or ""
            value = (
                f"{region}{remote_street.group(2)}, улица {remote_street.group(3)}, "
                f"{remote_street.group(4)}"
            )

        moscow_street = re.match(r"^Москва,?\s+(.+?)\s+ул\.\s+д\.\s+(.+)$", value)
        if moscow_street is not None:
            value = f"Москва, улица {moscow_street.group(1)}, {moscow_street.group(2)}"
        moscow_passage = re.match(r"^Москва,?\s+(.+?)\s+пр-зд\.\s+д\.\s+(.+)$", value)
        if moscow_passage is not None:
            value = f"Москва, {moscow_passage.group(1)} проезд, {moscow_passage.group(2)}"

        replacements = {
            "пр-кт.": "проспект ",
            "ул.": "улица ",
            "пер.": "переулок ",
            "наб.": "набережная ",
            "б-р.": "бульвар ",
            "ш.": "шоссе ",
        }
        for source, replacement in replacements.items():
            value = value.replace(source, replacement)
        value = re.sub(r"(?<=,\s)ул\s+", "улица ", value)
        value = re.sub(
            r"(?<=,\s)проезд\.?\s*([^,]+)",
            lambda match: f"{match.group(1).strip()} проезд",
            value,
        )
        value = re.sub(
            r"([А-ЯЁ][а-яё-]+)\s+(\d+-[йя])\s+проезд",
            r"\2 \1 проезд",
            value,
        )
        value = re.sub(r",\s*д\.?\s*", ", ", value)
        value = re.sub(r"\s+к\s+(\d+)", r"к\1", value)
        value = re.sub(r"с\s+(\d+)", r"с\1", value)
        value = re.sub(r"\s*,\s*", ", ", value)
        return " ".join(value.split())
