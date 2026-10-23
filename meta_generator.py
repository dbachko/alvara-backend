"""Metadata orchestration over validated chain data and local assets."""

from __future__ import annotations

from typing import Any

from artifacts_keeper import ArtifactsKeeper
from collection_settings import CollectionSettings
from errors import ArtifactNotFound, InvalidGenome, TokenNotFound, UpstreamUnavailable
from genome import TokenGenome, decode_genome
from smart_client import TokenDataSource
from token_state import TokenState, TokenStatus

TOKEN_NAME = "Alvara #"

_DESCRIPTIONS = {
    "cool": (
        "The category includes 4,500 photos. It’s focused on not related to time or "
        "place everyday moments of Alvara’s life. Generally, she led a quiet, measured "
        "life at that time, so she was dressed in the typical clothes of that time and place."
    ),
    "hot": (
        "The category includes 2,500 photos. This group reveals a little more of "
        "Alvara’s feminine side. Any couturier in the Commonwealth of Planets would envy "
        "such a collection of lingerie. Alvara is said to have a separate room in her home "
        "for such clothes."
    ),
    "glorious": (
        "The category consists of 2,000 photos. There were large-scale wars before and, "
        "not surprisingly, even after the war with the Iguns. Alvara has been involved "
        "in many, many wars. This category contains photos of her service as a common "
        "private soldier."
    ),
    "terrific": (
        "The category contains 900 photos. Alvara was sometimes bored of being an ordinary "
        "soldier. She could demonstrate her leadership and fighting skills, which instantly "
        "brought her to the forefront of military conflict. People trusted her to take "
        "command of another elite squad to solve problems of high complexity. This kind "
        "of squad had state-of-the-art equipment."
    ),
    "divine": (
        "The category has 100 photos. To be the most powerful entity of the Commonwealth "
        "of Planets and not take full advantage of it, at least locally in some lost corner "
        "of the galaxy, no, that’s not about Alvara. There were times when she wanted to "
        "be the center of attention. To turn the tide of a lost war on her own. To find a "
        "backward planet and, like Prometheus, give them the flame of genuine knowledge. "
        "Alvara, in these photos, is like a Greek goddess of war, enlightenment, or wisdom."
    ),
}


class MetaGenerator:
    def __init__(
        self,
        keeper: ArtifactsKeeper,
        state: TokenState,
        source: TokenDataSource,
        settings: CollectionSettings,
        public_base_url: str,
    ) -> None:
        self.keeper = keeper
        self.state = state
        self.source = source
        self.settings = settings
        self.public_base_url = public_base_url.rstrip("/")

    def _metadata_json(self, genome: TokenGenome) -> dict[str, Any]:
        category = self.settings.categories[genome.category_id]
        attributes: list[dict[str, str]] = [{"trait_type": "category", "value": category.name}]
        for attribute_index, option_index in enumerate(genome.options):
            attribute = category.attributes[attribute_index]
            attributes.append(
                {
                    "trait_type": attribute.name,
                    "value": attribute.options[option_index].name,
                }
            )
        return {
            "description": _DESCRIPTIONS.get(
                category.name, f"Alvara collection category: {category.name}."
            ),
            "image": f"{self.public_base_url}/image/{genome.token_id}",
            "name": f"{TOKEN_NAME}{genome.token_id}",
            # Preserved for legacy clients. This endpoint returns the 3000px render.
            "external_url": f"{self.public_base_url}/external/{genome.token_id}",
            "attributes": attributes,
        }

    async def _read_genome(self, token_id: int) -> TokenGenome:
        try:
            raw = await self.source.get_token_data(token_id)
        except (TokenNotFound, InvalidGenome, UpstreamUnavailable):
            raise
        except Exception as exc:
            raise UpstreamUnavailable("token data source failed") from exc
        return decode_genome(raw, token_id, self.settings)

    async def meta(self, token_id: int) -> dict[str, Any]:
        async with self.state.locks[token_id]:
            try:
                genome = await self._read_genome(token_id)
            except TokenNotFound:
                await self.keeper.tombstone(token_id)
                raise
            record = self.state.tokens[token_id]
            if record.data == genome.raw and self.keeper.bundle_exists(token_id):
                try:
                    return await self.keeper.token_meta_content(token_id)
                except ArtifactNotFound:
                    pass

            content = self._metadata_json(genome)
            await self.keeper.create_bundle(genome, content)
            previous_data = record.data
            previous_status = record.status
            record.data = genome.raw
            record.status = TokenStatus.REROLLED if genome.rerolled else TokenStatus.NOT_REROLLED
            try:
                await self.state.dump_token_state(token_id)
            except Exception:
                # Do not allow an in-memory cache hit to conceal a failed state write.
                record.data = previous_data
                record.status = previous_status
                raise
            return content
