using QRCoder;

namespace Reva.Desktop.Devices;

/// <summary>Draws text as a QR code image. Pure and offline: nothing is sent anywhere.</summary>
public interface IQrEncoder
{
    /// <summary>A PNG: dark modules on a light tile with a quiet zone, readable by a phone camera.</summary>
    byte[] EncodePng(string text);
}

/// <summary>QRCoder (MIT, https://github.com/codebude/QRCoder), pinned in Reva.Desktop.csproj. Only its managed
/// PNG writer is used; it makes no network calls.</summary>
public sealed class QrCoderEncoder : IQrEncoder
{
    // Design tokens: ground #0E1013 for the modules, text #ECEEF1 for the tile (about 15:1 contrast).
    private static readonly byte[] Dark = { 0x0E, 0x10, 0x13, 0xFF };
    private static readonly byte[] Light = { 0xEC, 0xEE, 0xF1, 0xFF };

    public byte[] EncodePng(string text)
    {
        using var generator = new QRCodeGenerator();
        using var data = generator.CreateQrCode(text, QRCodeGenerator.ECCLevel.M);
        return new PngByteQRCode(data).GetGraphic(8, Dark, Light, drawQuietZones: true);
    }
}
